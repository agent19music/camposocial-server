from flask import Blueprint, render_template_string, jsonify
from flask import current_app
import inspect

api_explorer_bp = Blueprint('api_explorer', __name__)

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>API Explorer — CampoSocial</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        :root {
            --bg-primary: #000000;
            --bg-secondary: #0a0a0a;
            --bg-tertiary: #161616;
            --surface: #1c1c1e;
            --surface-hover: #2c2c2e;
            --text-primary: #ffffff;
            --text-secondary: #86868b;
            --text-tertiary: #515154;
            --accent: #F76F53;
            --accent-hover: #F55A3C;
            --accent-light: #FAA294;
            --accent-blend: #F7B3A7;
            --success: #34c759;
            --warning: #ff9500;
            --danger: #ff3b30;
            --info: #F7F7F7;
            --border: rgba(255, 255, 255, 0.1);
            --border-light: rgba(255, 255, 255, 0.05);
            --shadow-sm: 0 2px 8px rgba(0, 0, 0, 0.3);
            --shadow-md: 0 8px 24px rgba(0, 0, 0, 0.4);
            --shadow-lg: 0 16px 48px rgba(0, 0, 0, 0.5);
            --shadow-glow: 0 0 40px rgba(247, 111, 83, 0.2);
        }
        
        @media (prefers-color-scheme: light) {
            :root {
                --bg-primary: #ffffff;
                --bg-secondary: #fbfbfd;
                --bg-tertiary: #f7f7f7;
                --surface: #ffffff;
                --surface-hover: #f7f7f7;
                --text-primary: #1d1d1f;
                --text-secondary: #86868b;
                --text-tertiary: #a1a1a6;
                --accent: #F76F53;
                --accent-hover: #F55A3C;
                --accent-light: #FDDBD5;
                --accent-blend: #FCE8E4;
                --border: rgba(0, 0, 0, 0.1);
                --border-light: rgba(0, 0, 0, 0.05);
                --shadow-sm: 0 2px 8px rgba(0, 0, 0, 0.08);
                --shadow-md: 0 8px 24px rgba(0, 0, 0, 0.12);
                --shadow-lg: 0 16px 48px rgba(0, 0, 0, 0.16);
                --shadow-glow: 0 0 40px rgba(247, 111, 83, 0.15);
            }
        }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'SF Pro Display', 'SF Pro Text', 'Helvetica Neue', Helvetica, Arial, sans-serif;
            background: var(--bg-primary);
            color: var(--text-primary);
            line-height: 1.47059;
            font-weight: 400;
            letter-spacing: -.022em;
            min-height: 100vh;
            -webkit-font-smoothing: antialiased;
            -moz-osx-font-smoothing: grayscale;
        }
        
        /* Smooth scrolling */
        html {
            scroll-behavior: smooth;
        }
        
        /* Custom scrollbar */
        ::-webkit-scrollbar {
            width: 8px;
            height: 8px;
        }
        
        ::-webkit-scrollbar-track {
            background: transparent;
        }
        
        ::-webkit-scrollbar-thumb {
            background: var(--text-tertiary);
            border-radius: 8px;
        }
        
        ::-webkit-scrollbar-thumb:hover {
            background: var(--text-secondary);
        }
        
        .container {
            max-width: 1200px;
            margin: 0 auto;
            padding: 0 24px;
        }
        
        /* Navigation Bar */
        .nav-bar {
            position: sticky;
            top: 0;
            background: rgba(0, 0, 0, 0.8);
            backdrop-filter: saturate(180%) blur(20px);
            -webkit-backdrop-filter: saturate(180%) blur(20px);
            border-bottom: 1px solid var(--border);
            z-index: 1000;
            transition: background 0.3s ease;
        }
        
        @media (prefers-color-scheme: light) {
            .nav-bar {
                background: rgba(255, 255, 255, 0.8);
            }
        }
        
        .nav-content {
            display: flex;
            align-items: center;
            justify-content: space-between;
            height: 48px;
            padding: 0 24px;
            max-width: 1200px;
            margin: 0 auto;
        }
        
        .nav-logo {
            font-size: 18px;
            font-weight: 600;
            color: var(--text-primary);
            text-decoration: none;
            display: flex;
            align-items: center;
            gap: 8px;
        }
        
        .nav-actions {
            display: flex;
            align-items: center;
            gap: 16px;
        }
        
        .theme-toggle {
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 20px;
            padding: 6px 12px;
            cursor: pointer;
            color: var(--text-secondary);
            font-size: 14px;
            transition: all 0.2s ease;
        }
        
        .theme-toggle:hover {
            background: var(--surface-hover);
            color: var(--text-primary);
        }
        
        /* Hero Section */
        .hero {
            padding: 80px 0 48px;
            text-align: center;
            background: linear-gradient(180deg, transparent 0%, var(--bg-secondary) 100%);
        }
        
        .hero h1 {
            font-size: 56px;
            font-weight: 700;
            letter-spacing: -.005em;
            line-height: 1.07143;
            margin-bottom: 16px;
            background: linear-gradient(90deg, var(--text-primary) 0%, var(--text-secondary) 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
        }
        
        @media (max-width: 768px) {
            .hero h1 {
                font-size: 40px;
            }
        }
        
        .hero-subtitle {
            font-size: 21px;
            line-height: 1.381;
            font-weight: 400;
            letter-spacing: .011em;
            color: var(--text-secondary);
            max-width: 600px;
            margin: 0 auto;
        }
        
        /* Stats Cards */
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
            gap: 16px;
            margin-top: 48px;
        }
        
        .stat-card {
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 16px;
            padding: 24px;
            position: relative;
            overflow: hidden;
            transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
        }
        
        .stat-card::before {
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            height: 4px;
            background: linear-gradient(90deg, var(--accent) 0%, var(--accent-blend) 100%);
            transform: scaleX(0);
            transform-origin: left;
            transition: transform 0.3s ease;
        }
        
        .stat-card:hover {
            transform: translateY(-2px);
            box-shadow: var(--shadow-md);
            border-color: var(--accent);
        }
        
        .stat-card:hover::before {
            transform: scaleX(1);
        }
        
        .stat-value {
            font-size: 48px;
            font-weight: 700;
            line-height: 1;
            color: var(--accent);
            margin-bottom: 8px;
        }
        
        .stat-label {
            color: var(--text-secondary);
            font-size: 14px;
            font-weight: 500;
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }
        
        /* Search and Filters */
        .controls {
            background: var(--bg-secondary);
            border-radius: 20px;
            padding: 24px;
            margin: 32px 0;
            border: 1px solid var(--border-light);
        }
        
        .search-wrapper {
            position: relative;
            margin-bottom: 20px;
        }
        
        .search-icon {
            position: absolute;
            left: 16px;
            top: 50%;
            transform: translateY(-50%);
            color: var(--text-tertiary);
            pointer-events: none;
        }
        
        .search-input {
            width: 100%;
            padding: 14px 16px 14px 44px;
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 12px;
            font-size: 16px;
            color: var(--text-primary);
            transition: all 0.2s ease;
        }
        
        .search-input:focus {
            outline: none;
            border-color: var(--accent);
            box-shadow: 0 0 0 3px rgba(247, 111, 83, 0.1);
        }
        
        .search-input::placeholder {
            color: var(--text-tertiary);
        }
        
        .filter-chips {
            display: flex;
            gap: 8px;
            flex-wrap: wrap;
        }
        
        .chip {
            padding: 8px 16px;
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 20px;
            font-size: 14px;
            font-weight: 500;
            color: var(--text-secondary);
            cursor: pointer;
            transition: all 0.2s ease;
            white-space: nowrap;
        }
        
        .chip:hover {
            background: var(--surface-hover);
            color: var(--text-primary);
            transform: scale(1.05);
        }
        
        .chip.active {
            background: var(--accent);
            color: white;
            border-color: var(--accent);
        }
        
        .chip.active:hover {
            background: var(--accent-hover);
            border-color: var(--accent-hover);
        }
        
        /* Endpoints Grid */
        .endpoints-container {
            display: grid;
            gap: 24px;
            margin-bottom: 80px;
        }
        
        .endpoint-group {
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 20px;
            overflow: hidden;
            transition: all 0.3s ease;
        }
        
        .endpoint-group:hover {
            box-shadow: var(--shadow-md);
        }
        
        .group-header {
            padding: 20px 24px;
            background: linear-gradient(135deg, var(--bg-tertiary) 0%, var(--surface) 100%);
            border-bottom: 1px solid var(--border);
            font-size: 18px;
            font-weight: 600;
            color: var(--text-primary);
            display: flex;
            align-items: center;
            justify-content: space-between;
        }
        
        .group-count {
            background: var(--bg-secondary);
            padding: 4px 12px;
            border-radius: 12px;
            font-size: 12px;
            font-weight: 500;
            color: var(--text-secondary);
        }
        
        .endpoint {
            padding: 20px 24px;
            border-bottom: 1px solid var(--border-light);
            transition: all 0.2s ease;
            cursor: pointer;
            position: relative;
        }
        
        .endpoint::before {
            content: '';
            position: absolute;
            left: 0;
            top: 0;
            bottom: 0;
            width: 3px;
            background: var(--accent);
            transform: scaleY(0);
            transition: transform 0.2s ease;
        }
        
        .endpoint:hover {
            background: var(--surface-hover);
        }
        
        .endpoint:hover::before {
            transform: scaleY(1);
        }
        
        .endpoint:last-child {
            border-bottom: none;
        }
        
        .endpoint-header {
            display: flex;
            align-items: center;
            gap: 12px;
            margin-bottom: 8px;
            flex-wrap: wrap;
        }
        
        .method-badge {
            padding: 4px 10px;
            border-radius: 6px;
            font-size: 11px;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            min-width: 50px;
        }
        
        .method-badge.GET {
            background: rgba(52, 199, 89, 0.15);
            color: var(--success);
        }
        
        .method-badge.POST {
            background: rgba(247, 111, 83, 0.15);
            color: var(--accent);
        }
        
        .method-badge.PUT {
            background: rgba(255, 149, 0, 0.15);
            color: var(--warning);
        }
        
        .method-badge.DELETE {
            background: rgba(255, 59, 48, 0.15);
            color: var(--danger);
        }
        
        .method-badge.PATCH {
            background: rgba(90, 200, 250, 0.15);
            color: var(--info);
        }
        
        .endpoint-path {
            font-family: 'SF Mono', Monaco, 'Cascadia Code', 'Roboto Mono', Consolas, 'Courier New', monospace;
            font-size: 14px;
            color: var(--text-primary);
            flex: 1;
            word-break: break-all;
        }
        
        .auth-indicator {
            display: inline-flex;
            align-items: center;
            gap: 4px;
            padding: 4px 8px;
            background: rgba(255, 149, 0, 0.15);
            color: var(--warning);
            border-radius: 6px;
            font-size: 11px;
            font-weight: 600;
        }
        
        .endpoint-description {
            color: var(--text-secondary);
            font-size: 14px;
            line-height: 1.5;
            margin-bottom: 12px;
        }
        
        .endpoint-params {
            display: flex;
            gap: 8px;
            flex-wrap: wrap;
        }
        
        .param-chip {
            padding: 4px 10px;
            background: var(--bg-secondary);
            border: 1px solid var(--border-light);
            border-radius: 8px;
            font-size: 12px;
            font-family: 'SF Mono', Monaco, 'Cascadia Code', 'Roboto Mono', Consolas, 'Courier New', monospace;
            color: var(--text-secondary);
        }
        
        .param-chip.required {
            background: rgba(255, 59, 48, 0.1);
            border-color: rgba(255, 59, 48, 0.2);
            color: var(--danger);
        }
        
        /* Empty State */
        .empty-state {
            text-align: center;
            padding: 80px 24px;
            color: var(--text-tertiary);
        }
        
        .empty-icon {
            font-size: 48px;
            margin-bottom: 16px;
            opacity: 0.5;
        }
        
        .empty-title {
            font-size: 24px;
            font-weight: 600;
            color: var(--text-secondary);
            margin-bottom: 8px;
        }
        
        .empty-message {
            font-size: 16px;
            color: var(--text-tertiary);
        }
        
        /* Footer */
        footer {
            padding: 48px 0;
            text-align: center;
            border-top: 1px solid var(--border-light);
            background: var(--bg-secondary);
        }
        
        .footer-content {
            color: var(--text-tertiary);
            font-size: 14px;
        }
        
        .footer-content a {
            color: var(--accent);
            text-decoration: none;
        }
        
        .footer-content a:hover {
            text-decoration: underline;
        }
        
        /* Animations */
        @keyframes fadeIn {
            from {
                opacity: 0;
                transform: translateY(20px);
            }
            to {
                opacity: 1;
                transform: translateY(0);
            }
        }
        
        .fade-in {
            animation: fadeIn 0.6s ease-out;
        }
        
        @keyframes pulse {
            0%, 100% {
                opacity: 1;
            }
            50% {
                opacity: 0.5;
            }
        }
        
        .loading {
            animation: pulse 2s infinite;
        }
        
        /* Responsive Design */
        @media (max-width: 768px) {
            .container {
                padding: 0 16px;
            }
            
            .hero {
                padding: 48px 0 32px;
            }
            
            .stats-grid {
                grid-template-columns: 1fr;
            }
            
            .endpoint-path {
                font-size: 12px;
            }
        }
    </style>
</head>
<body>
    <!-- Navigation Bar -->
    <nav class="nav-bar">
        <div class="nav-content">
            <a href="#" class="nav-logo">
                <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <circle cx="12" cy="12" r="10"></circle>
                    <polyline points="12 6 12 12 16 14"></polyline>
                </svg>
                <span>CampoSocial API</span>
            </a>
            <div class="nav-actions">
                <button class="theme-toggle" onclick="toggleTheme()">
                    <span id="themeIcon">🌙</span>
                </button>
            </div>
        </div>
    </nav>
    
    <!-- Hero Section -->
    <div class="hero">
        <div class="container">
            <h1 class="fade-in">API Explorer</h1>
            <p class="hero-subtitle fade-in">Discover and test your REST API endpoints with an elegant, intuitive interface</p>
            
            <div class="stats-grid fade-in">
                <div class="stat-card">
                    <div class="stat-value" id="totalEndpoints">0</div>
                    <div class="stat-label">Endpoints</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value" id="totalGroups">0</div>
                    <div class="stat-label">Groups</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value" id="authEndpoints">0</div>
                    <div class="stat-label">Protected</div>
                </div>
            </div>
        </div>
    </div>
    
    <div class="container">
        <!-- Search and Filters -->
        <div class="controls fade-in">
            <div class="search-wrapper">
                <svg class="search-icon" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <circle cx="11" cy="11" r="8"></circle>
                    <path d="m21 21-4.35-4.35"></path>
                </svg>
                <input type="text" class="search-input" id="searchInput" placeholder="Search endpoints, methods, or descriptions..." />
            </div>
            <div class="filter-chips">
                <button class="chip active" data-filter="all">All Methods</button>
                <button class="chip" data-filter="GET">GET</button>
                <button class="chip" data-filter="POST">POST</button>
                <button class="chip" data-filter="PUT">PUT</button>
                <button class="chip" data-filter="DELETE">DELETE</button>
                <button class="chip" data-filter="auth">
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="margin-right: 4px;">
                        <rect x="3" y="11" width="18" height="11" rx="2" ry="2"></rect>
                        <path d="M7 11V7a5 5 0 0 1 10 0v4"></path>
                    </svg>
                    Protected
                </button>
            </div>
        </div>
        
        <!-- Endpoints Container -->
        <div class="endpoints-container fade-in" id="endpointsContainer">
            <!-- Loading State -->
            <div class="loading" style="text-align: center; padding: 40px; color: var(--text-tertiary);">
                Loading endpoints...
            </div>
        </div>
    </div>
    
    <!-- Footer -->
    <footer>
        <div class="footer-content">
            <p>Built with precision and care by the <a href="#">CampoSocial Team</a></p>
            <p style="margin-top: 8px; font-size: 12px;">© 2024 CampoSocial. All rights reserved.</p>
        </div>
    </footer>
    
    <script>
        let allEndpoints = [];
        let isDarkMode = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
        
        // Theme toggle functionality
        function toggleTheme() {
            isDarkMode = !isDarkMode;
            document.documentElement.style.setProperty('color-scheme', isDarkMode ? 'dark' : 'light');
            updateThemeIcon();
            
            // Update CSS variables for manual theme switching
            if (isDarkMode) {
                document.documentElement.style.setProperty('--bg-primary', '#000000');
                document.documentElement.style.setProperty('--bg-secondary', '#0a0a0a');
                document.documentElement.style.setProperty('--bg-tertiary', '#161616');
                document.documentElement.style.setProperty('--surface', '#1c1c1e');
                document.documentElement.style.setProperty('--surface-hover', '#2c2c2e');
                document.documentElement.style.setProperty('--text-primary', '#ffffff');
                document.documentElement.style.setProperty('--text-secondary', '#86868b');
                document.documentElement.style.setProperty('--text-tertiary', '#515154');
            } else {
                document.documentElement.style.setProperty('--bg-primary', '#ffffff');
                document.documentElement.style.setProperty('--bg-secondary', '#fbfbfd');
                document.documentElement.style.setProperty('--bg-tertiary', '#f5f5f7');
                document.documentElement.style.setProperty('--surface', '#ffffff');
                document.documentElement.style.setProperty('--surface-hover', '#f5f5f7');
                document.documentElement.style.setProperty('--text-primary', '#1d1d1f');
                document.documentElement.style.setProperty('--text-secondary', '#86868b');
                document.documentElement.style.setProperty('--text-tertiary', '#a1a1a6');
            }
        }
        
        function updateThemeIcon() {
            const icon = document.getElementById('themeIcon');
            icon.textContent = isDarkMode ? '☀️' : '🌙';
        }
        
        async function loadEndpoints() {
            try {
                const response = await fetch('/api-explorer/data');
                const data = await response.json();
                allEndpoints = data.endpoints;
                renderEndpoints(allEndpoints);
                updateStats(allEndpoints);
            } catch (error) {
                console.error('Failed to load endpoints:', error);
                showErrorState();
            }
        }
        
        function updateStats(endpoints) {
            const totalEndpoints = endpoints.reduce((sum, group) => sum + group.endpoints.length, 0);
            const totalGroups = endpoints.length;
            const authEndpoints = endpoints.reduce((sum, group) => 
                sum + group.endpoints.filter(e => e.requires_auth).length, 0);
            
            // Animate counter updates
            animateValue('totalEndpoints', 0, totalEndpoints, 1000);
            animateValue('totalGroups', 0, totalGroups, 1000);
            animateValue('authEndpoints', 0, authEndpoints, 1000);
        }
        
        function animateValue(id, start, end, duration) {
            const element = document.getElementById(id);
            const range = end - start;
            const increment = end > start ? 1 : -1;
            const stepTime = Math.abs(Math.floor(duration / range));
            let current = start;
            
            const timer = setInterval(() => {
                current += increment;
                element.textContent = current;
                if (current == end) {
                    clearInterval(timer);
                }
            }, stepTime);
        }
        
        function renderEndpoints(endpoints) {
            const container = document.getElementById('endpointsContainer');
            
            if (endpoints.length === 0) {
                container.innerHTML = `
                    <div class="empty-state">
                        <div class="empty-icon">🔍</div>
                        <div class="empty-title">No endpoints found</div>
                        <div class="empty-message">Try adjusting your search or filters</div>
                    </div>
                `;
                return;
            }
            
            container.innerHTML = endpoints.map(group => `
                <div class="endpoint-group">
                    <div class="group-header">
                        <span>${group.name}</span>
                        <span class="group-count">${group.endpoints.length}</span>
                    </div>
                    ${group.endpoints.map(endpoint => `
                        <div class="endpoint" data-method="${endpoint.method}" data-auth="${endpoint.requires_auth}">
                            <div class="endpoint-header">
                                <span class="method-badge ${endpoint.method}">${endpoint.method}</span>
                                <span class="endpoint-path">${endpoint.path}</span>
                                ${endpoint.requires_auth ? `
                                    <span class="auth-indicator">
                                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                                            <rect x="3" y="11" width="18" height="11" rx="2" ry="2"></rect>
                                            <path d="M7 11V7a5 5 0 0 1 10 0v4"></path>
                                        </svg>
                                        Protected
                                    </span>
                                ` : ''}
                            </div>
                            ${endpoint.description ? `<div class="endpoint-description">${endpoint.description}</div>` : ''}
                            ${endpoint.parameters && endpoint.parameters.length > 0 ? `
                                <div class="endpoint-params">
                                    ${endpoint.parameters.map(param => 
                                        `<span class="param-chip ${param.required ? 'required' : ''}">${param.name}${param.required ? ' *' : ''}</span>`
                                    ).join('')}
                                </div>
                            ` : ''}
                        </div>
                    `).join('')}
                </div>
            `).join('');
        }
        
        function showErrorState() {
            const container = document.getElementById('endpointsContainer');
            container.innerHTML = `
                <div class="empty-state">
                    <div class="empty-icon">⚠️</div>
                    <div class="empty-title">Failed to load endpoints</div>
                    <div class="empty-message">Please check your connection and try again</div>
                </div>
            `;
        }
        
        // Search functionality with debounce
        let searchTimeout;
        document.getElementById('searchInput').addEventListener('input', (e) => {
            clearTimeout(searchTimeout);
            searchTimeout = setTimeout(() => {
                const searchTerm = e.target.value.toLowerCase();
                
                if (!searchTerm) {
                    renderEndpoints(allEndpoints);
                    return;
                }
                
                const filtered = allEndpoints.map(group => ({
                    ...group,
                    endpoints: group.endpoints.filter(endpoint => 
                        endpoint.path.toLowerCase().includes(searchTerm) ||
                        endpoint.method.toLowerCase().includes(searchTerm) ||
                        (endpoint.description && endpoint.description.toLowerCase().includes(searchTerm))
                    )
                })).filter(group => group.endpoints.length > 0);
                
                renderEndpoints(filtered);
            }, 300);
        });
        
        // Filter chips
        document.querySelectorAll('.chip').forEach(btn => {
            btn.addEventListener('click', (e) => {
                // Handle click on SVG or text inside button
                const target = e.target.closest('.chip');
                document.querySelectorAll('.chip').forEach(b => b.classList.remove('active'));
                target.classList.add('active');
                
                const filter = target.dataset.filter;
                
                if (filter === 'all') {
                    renderEndpoints(allEndpoints);
                    return;
                }
                
                const filtered = allEndpoints.map(group => ({
                    ...group,
                    endpoints: group.endpoints.filter(endpoint => {
                        if (filter === 'auth') {
                            return endpoint.requires_auth;
                        }
                        return endpoint.method === filter;
                    })
                })).filter(group => group.endpoints.length > 0);
                
                renderEndpoints(filtered);
            });
        });
        
        // Keyboard shortcuts
        document.addEventListener('keydown', (e) => {
            // Focus search on '/' key
            if (e.key === '/' && document.activeElement !== document.getElementById('searchInput')) {
                e.preventDefault();
                document.getElementById('searchInput').focus();
            }
            // Clear search on Escape
            if (e.key === 'Escape' && document.activeElement === document.getElementById('searchInput')) {
                document.getElementById('searchInput').value = '';
                renderEndpoints(allEndpoints);
            }
        });
        
        // Initialize theme
        updateThemeIcon();
        
        // Load endpoints on page load
        loadEndpoints();
    </script>
</body>
</html>
"""

@api_explorer_bp.route('/api-explorer')
def api_explorer():
    """Display the API explorer interface"""
    return render_template_string(HTML_TEMPLATE)

@api_explorer_bp.route('/api-explorer/data')
def api_explorer_data():
    """Return API endpoints data as JSON"""
    endpoints_by_group = {}
    
    # Get all registered rules
    for rule in current_app.url_map.iter_rules():
        # Skip static files and internal routes
        if rule.endpoint == 'static' or not rule.endpoint:
            continue
            
        # Get the blueprint name
        parts = rule.endpoint.split('.')
        group_name = parts[0] if len(parts) > 1 else 'main'
        
        # Clean up group name
        if group_name == 'api_doc':
            group_name = 'Documentation'
        elif group_name == 'auth_bp':
            group_name = 'Authentication'
        elif group_name == 'user_bp':
            group_name = 'Users'
        elif group_name == 'event_bp':
            group_name = 'Events'
        elif group_name == 'marketplace_bp':
            group_name = 'Marketplace'
        elif group_name == 'yap_bp':
            group_name = 'Yaps'
        elif group_name == 'friends_bp':
            group_name = 'Friends'
        elif group_name == 'api_explorer':
            group_name = 'API Explorer'
        else:
            group_name = group_name.replace('_', ' ').title()
        
        if group_name not in endpoints_by_group:
            endpoints_by_group[group_name] = []
        
        # Determine if auth is required based on common patterns
        requires_auth = any(keyword in str(rule) for keyword in [
            'profile', 'update', 'delete', 'add', 'logout', 'authenticated',
            'friends', 'conversations', 'cart', 'comment', 'request'
        ])
        
        # Get method information
        methods = list(rule.methods - {'HEAD', 'OPTIONS'})
        
        for method in methods:
            # Extract parameters from the path
            parameters = []
            if '<' in str(rule):
                import re
                params = re.findall(r'<(?:int:|string:|float:)?(\w+)>', str(rule))
                parameters = [{'name': p, 'required': True} for p in params]
            
            # Try to get description from function docstring
            description = ''
            try:
                if rule.endpoint:
                    view_func = current_app.view_functions.get(rule.endpoint)
                    if view_func and hasattr(view_func, '__doc__'):
                        description = view_func.__doc__ or ''
                        description = description.strip()
            except:
                pass
            
            endpoints_by_group[group_name].append({
                'path': str(rule),
                'method': method,
                'endpoint': rule.endpoint,
                'requires_auth': requires_auth,
                'parameters': parameters,
                'description': description
            })
    
    # Convert to list format
    result = []
    for group_name, endpoints in sorted(endpoints_by_group.items()):
        result.append({
            'name': group_name,
            'endpoints': sorted(endpoints, key=lambda x: (x['path'], x['method']))
        })
    
    return jsonify({'endpoints': result})
