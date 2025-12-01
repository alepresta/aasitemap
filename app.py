from flask import Flask, render_template, request, jsonify
import requests
from urllib.parse import urlparse, urljoin
from bs4 import BeautifulSoup
import re
from collections import deque
import time
import threading
from queue import Queue
import json

app = Flask(__name__)


class SiteCrawler:
    def __init__(self, start_url, max_urls=100, max_threads=5):
        self.start_url = start_url
        self.max_urls = max_urls
        self.max_threads = max_threads
        self.visited_urls = set()
        self.urls_to_visit = deque([start_url])
        self.all_urls = set([start_url])
        self.domain = urlparse(start_url).netloc
        self.lock = threading.Lock()
        self.queue = Queue()
        self.running = True
        self.results = []

    def is_same_domain(self, url):
        try:
            return urlparse(url).netloc == self.domain
        except:
            return False

    def normalize_url(self, url):
        # Eliminar fragmentos y parámetros de query para URLs únicas
        parsed = urlparse(url)
        return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"

    def extract_links(self, html, base_url):
        soup = BeautifulSoup(html, 'html.parser')
        links = set()

        for tag in soup.find_all(['a', 'link']):
            href = tag.get('href')
            if href:
                # Convertir URL relativa a absoluta
                absolute_url = urljoin(base_url, href)
                # Normalizar la URL
                normalized_url = self.normalize_url(absolute_url)

                # Verificar si es del mismo dominio y es una página válida
                if (self.is_same_domain(normalized_url) and
                        not normalized_url.endswith(
                            ('.jpg', '.jpeg', '.png', '.gif', '.pdf', '.zip', '.css', '.js')) and
                        'mailto:' not in normalized_url and
                        'tel:' not in normalized_url):
                    links.add(normalized_url)

        return links

    def crawl_worker(self):
        while self.running and len(self.all_urls) < self.max_urls:
            try:
                url = self.queue.get(timeout=2)

                if url in self.visited_urls:
                    self.queue.task_done()
                    continue

                try:
                    headers = {
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                    }
                    response = requests.get(url, headers=headers, timeout=5, allow_redirects=True)

                    if response.status_code == 200:
                        with self.lock:
                            self.visited_urls.add(url)
                            self.results.append({
                                'url': url,
                                'status': response.status_code,
                                'title': BeautifulSoup(response.text[:1000], 'html.parser').title.string
                                if BeautifulSoup(response.text[:1000], 'html.parser').title else 'Sin título'
                            })

                        # Extraer enlaces
                        new_links = self.extract_links(response.text, url)

                        with self.lock:
                            for link in new_links:
                                if link not in self.all_urls and len(self.all_urls) < self.max_urls:
                                    self.all_urls.add(link)
                                    self.queue.put(link)

                except Exception as e:
                    print(f"Error al procesar {url}: {str(e)}")
                    with self.lock:
                        self.visited_urls.add(url)

                self.queue.task_done()
                time.sleep(0.5)  # Respeta el sitio web

            except Exception as e:
                continue

    def crawl(self):
        # Inicializar la cola con la URL inicial
        self.queue.put(self.start_url)

        # Crear y empezar workers
        threads = []
        for _ in range(min(self.max_threads, self.max_urls)):
            thread = threading.Thread(target=self.crawl_worker)
            thread.daemon = True
            thread.start()
            threads.append(thread)

        # Esperar a que se procesen todas las URLs o alcanzar el límite
        self.queue.join()
        self.running = False

        # Esperar a que todos los threads terminen
        for thread in threads:
            thread.join(timeout=1)

        return {
            'domain': self.domain,
            'total_pages': len(self.all_urls),
            'visited_pages': len(self.visited_urls),
            'pages': sorted(list(self.all_urls)),
            'detailed_results': self.results
        }


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/analyze', methods=['POST'])
def analyze():
    try:
        data = request.get_json()
        domain = data.get('domain', '').strip()

        if not domain:
            return jsonify({'error': 'Por favor, ingresa un dominio'}), 400

        # Asegurar que tenga el protocolo http/https
        if not domain.startswith(('http://', 'https://')):
            domain = 'https://' + domain

        # Validar formato de URL
        parsed = urlparse(domain)
        if not parsed.netloc:
            return jsonify({'error': 'Dominio inválido'}), 400

        print(f"Iniciando análisis de: {domain}")

        # Crear y ejecutar el crawler
        crawler = SiteCrawler(domain, max_urls=50, max_threads=3)
        result = crawler.crawl()

        return jsonify(result)

    except Exception as e:
        print(f"Error en analyze: {str(e)}")
        return jsonify({'error': f'Error interno: {str(e)}'}), 500


@app.route('/api/sitemap/<path:domain>')
def api_sitemap(domain):
    try:
        if not domain.startswith(('http://', 'https://')):
            domain = 'https://' + domain

        # Intentar obtener el sitemap.xml primero
        sitemap_url = urljoin(domain, '/sitemap.xml')
        try:
            response = requests.get(sitemap_url, timeout=5)
            if response.status_code == 200:
                soup = BeautifulSoup(response.content, 'xml')
                urls = [loc.text for loc in soup.find_all('loc')]

                return jsonify({
                    'domain': domain,
                    'total_pages': len(urls),
                    'source': 'sitemap.xml',
                    'pages': urls[:100]  # Limitar a 100 para no sobrecargar
                })
        except:
            pass

        # Si no hay sitemap, usar el crawler básico
        crawler = SiteCrawler(domain, max_urls=30, max_threads=2)
        result = crawler.crawl()

        return jsonify(result)

    except Exception as e:
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=6000, debug=True)