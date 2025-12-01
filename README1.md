Te ayudo a crear una aplicación web en Python con Flask que analice un dominio y extraiga todas las URLs. Aquí tienes una solución completa:
1. Primero, instala las dependencias necesarias

En tu VPS Ubuntu 22.04, ejecuta:
bash

# Actualizar sistema
sudo apt update
sudo apt upgrade -y

# Instalar Python y pip
sudo apt install python3 python3-pip python3-venv -y

# Instalar otras dependencias útiles
sudo apt install git curl -y

2. Estructura del proyecto
bash

mkdir sitemap-analyzer
cd sitemap-analyzer
python3 -m venv venv
source venv/bin/activate

3. Archivo requirements.txt
txt

Flask==3.0.0
requests==2.31.0
beautifulsoup4==4.12.2
lxml==4.9.3
urllib3==2.0.7
python-dotenv==1.0.0

Instálalas con:
bash

pip install -r requirements.txt

4. Archivo principal app.py
python

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
                    not normalized_url.endswith(('.jpg', '.jpeg', '.png', '.gif', '.pdf', '.zip', '.css', '.js')) and
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

5. Archivo templates/index.html
html

<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Analizador de Dominios - Sitemap</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css">
    <style>
        body {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
        }
        .card {
            border-radius: 15px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.2);
            border: none;
        }
        .header {
            text-align: center;
            margin-bottom: 30px;
            color: white;
        }
        .header h1 {
            font-size: 2.5rem;
            margin-bottom: 10px;
        }
        .header p {
            font-size: 1.1rem;
            opacity: 0.9;
        }
        .result-card {
            background: #f8f9fa;
            border-left: 4px solid #667eea;
        }
        .url-list {
            max-height: 400px;
            overflow-y: auto;
        }
        .url-item {
            padding: 8px 12px;
            margin: 5px 0;
            background: white;
            border-radius: 5px;
            border-left: 3px solid #764ba2;
            word-break: break-all;
        }
        .stats {
            font-size: 1.2rem;
            font-weight: bold;
            color: #667eea;
        }
        .loading {
            display: none;
            text-align: center;
            padding: 20px;
        }
        .spinner {
            width: 50px;
            height: 50px;
            border: 5px solid #f3f3f3;
            border-top: 5px solid #667eea;
            border-radius: 50%;
            animation: spin 1s linear infinite;
            margin: 0 auto 15px;
        }
        @keyframes spin {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1><i class="fas fa-sitemap"></i> Analizador de Dominios</h1>
            <p>Descubre todas las páginas de cualquier sitio web</p>
        </div>
        
        <div class="card">
            <div class="card-body p-4">
                <div class="row">
                    <div class="col-md-8">
                        <div class="input-group input-group-lg">
                            <span class="input-group-text"><i class="fas fa-globe"></i></span>
                            <input type="text" id="domainInput" class="form-control" 
                                   placeholder="Ingresa un dominio (ej: ejemplo.com)" 
                                   value="http://85.31.224.145:6000/">
                            <button class="btn btn-primary" onclick="analyzeDomain()">
                                <i class="fas fa-search"></i> Analizar
                            </button>
                        </div>
                        <div class="form-text mt-2">
                            Puedes ingresar con o sin "https://". Ejemplos: google.com, https://example.org
                        </div>
                    </div>
                    <div class="col-md-4 d-flex align-items-center">
                        <div class="form-check form-switch">
                            <input class="form-check-input" type="checkbox" id="fastMode" checked>
                            <label class="form-check-label" for="fastMode">Modo rápido (limita a 50 páginas)</label>
                        </div>
                    </div>
                </div>
            </div>
        </div>

        <div class="loading" id="loading">
            <div class="spinner"></div>
            <h4>Analizando dominio...</h4>
            <p>Esto puede tomar unos segundos. Por favor, espera.</p>
            <div class="progress mt-3">
                <div class="progress-bar progress-bar-striped progress-bar-animated" 
                     style="width: 100%"></div>
            </div>
        </div>

        <div class="card mt-4 d-none" id="resultsCard">
            <div class="card-body p-4">
                <h3 class="mb-4"><i class="fas fa-chart-bar"></i> Resultados del Análisis</h3>
                
                <div class="row mb-4">
                    <div class="col-md-6">
                        <div class="result-card p-3">
                            <h5><i class="fas fa-info-circle"></i> Información del Dominio</h5>
                            <div id="domainInfo"></div>
                        </div>
                    </div>
                    <div class="col-md-6">
                        <div class="result-card p-3">
                            <h5><i class="fas fa-chart-pie"></i> Estadísticas</h5>
                            <div id="statsInfo" class="stats"></div>
                        </div>
                    </div>
                </div>

                <h5 class="mb-3"><i class="fas fa-list"></i> Páginas Encontradas (<span id="pageCount">0</span>)</h5>
                <div class="url-list" id="urlList"></div>
                
                <div class="mt-4">
                    <button class="btn btn-success" onclick="exportResults()">
                        <i class="fas fa-download"></i> Exportar Resultados
                    </button>
                    <button class="btn btn-outline-primary ms-2" onclick="copyToClipboard()">
                        <i class="fas fa-copy"></i> Copiar URLs
                    </button>
                </div>
            </div>
        </div>

        <div class="card mt-4">
            <div class="card-body">
                <h5><i class="fas fa-lightbulb"></i> ¿Cómo funciona?</h5>
                <ul>
                    <li>El sistema analiza el dominio ingresado y busca todas las páginas internas</li>
                    <li>Primero intenta localizar el archivo sitemap.xml</li>
                    <li>Si no existe, realiza un crawling inteligente del sitio</li>
                    <li>Respeta los tiempos del servidor y no sobrecarga el sitio objetivo</li>
                </ul>
            </div>
        </div>
    </div>

    <script>
        function analyzeDomain() {
            const domain = document.getElementById('domainInput').value.trim();
            const fastMode = document.getElementById('fastMode').checked;
            
            if (!domain) {
                alert('Por favor, ingresa un dominio');
                return;
            }

            // Mostrar loading
            document.getElementById('loading').style.display = 'block';
            document.getElementById('resultsCard').classList.add('d-none');

            // Configurar límites según el modo
            const maxUrls = fastMode ? 50 : 100;

            fetch('/analyze', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    domain: domain,
                    maxUrls: maxUrls
                })
            })
            .then(response => response.json())
            .then(data => {
                document.getElementById('loading').style.display = 'none';
                
                if (data.error) {
                    alert('Error: ' + data.error);
                    return;
                }

                displayResults(data);
            })
            .catch(error => {
                document.getElementById('loading').style.display = 'none';
                alert('Error al conectar con el servidor: ' + error.message);
            });
        }

        function displayResults(data) {
            // Mostrar información del dominio
            document.getElementById('domainInfo').innerHTML = `
                <p><strong>Dominio:</strong> ${data.domain}</p>
                <p><strong>Total de URLs encontradas:</strong> ${data.total_pages}</p>
                <p><strong>Páginas analizadas:</strong> ${data.visited_pages}</p>
            `;

            // Mostrar estadísticas
            document.getElementById('statsInfo').innerHTML = `
                <div class="text-success">
                    <i class="fas fa-check-circle"></i> 
                    ${data.total_pages} páginas identificadas
                </div>
            `;

            // Mostrar lista de URLs
            const urlList = document.getElementById('urlList');
            const pageCount = document.getElementById('pageCount');
            
            urlList.innerHTML = '';
            pageCount.textContent = data.pages.length;

            data.pages.forEach((url, index) => {
                const urlElement = document.createElement('div');
                urlElement.className = 'url-item';
                urlElement.innerHTML = `
                    <span class="badge bg-secondary me-2">${index + 1}</span>
                    <a href="${url}" target="_blank" class="text-decoration-none">
                        ${url}
                    </a>
                `;
                urlList.appendChild(urlElement);
            });

            // Mostrar la tarjeta de resultados
            document.getElementById('resultsCard').classList.remove('d-none');
        }

        function exportResults() {
            const urls = Array.from(document.querySelectorAll('.url-item a'))
                .map(a => a.href)
                .join('\n');
            
            const blob = new Blob([urls], { type: 'text/plain' });
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = 'sitemap_urls.txt';
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            window.URL.revokeObjectURL(url);
        }

        function copyToClipboard() {
            const urls = Array.from(document.querySelectorAll('.url-item a'))
                .map(a => a.href)
                .join('\n');
            
            navigator.clipboard.writeText(urls)
                .then(() => alert('URLs copiadas al portapapeles'))
                .catch(err => alert('Error al copiar: ' + err));
        }

        // Permitir Enter para enviar
        document.getElementById('domainInput').addEventListener('keypress', function(e) {
            if (e.key === 'Enter') {
                analyzeDomain();
            }
        });
    </script>
</body>
</html>

6. Archivo para ejecutar como servicio run.sh
bash

#!/bin/bash
cd /root/sitemap-analyzer
source venv/bin/activate
python app.py

7. Configurar como servicio systemd

Crea el archivo /etc/systemd/system/sitemap-analyzer.service:
ini

[Unit]
Description=Sitemap Analyzer Web Service
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/root/sitemap-analyzer
ExecStart=/root/sitemap-analyzer/venv/bin/python /root/sitemap-analyzer/app.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target

8. Comandos para configurar todo
bash

# Dar permisos de ejecución
chmod +x run.sh

# Recargar systemd y habilitar el servicio
sudo systemctl daemon-reload
sudo systemctl enable sitemap-analyzer.service
sudo systemctl start sitemap-analyzer.service

# Verificar que esté corriendo
sudo systemctl status sitemap-analyzer.service

# Ver logs
sudo journalctl -u sitemap-analyzer.service -f

9. Configurar firewall (si es necesario)
bash

# Permitir puerto 6000
sudo ufw allow 6000/tcp
sudo ufw reload

