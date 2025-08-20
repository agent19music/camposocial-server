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
    <title>CampoSocial API Explorer</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
        }
        
        .container {
            max-width: 1200px;
            margin: 0 auto;
        }
        
        header {
            background: white;
            border-radius: 15px;
            padding: 30px;
            margin-bottom: 30px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.1);
        }
        
        h1 {
            color: #333;
            font-size: 2.5em;
            margin-bottom: 10px;
        }
        
        .subtitle {
            color: #666;
            font-size: 1.1em;
        }
        
        .stats {
            display: flex;
            gap: 20px;
            margin-top: 20px;
        }
        
        .stat {
            background: #f8f9fa;
            padding: 15px 25px;
            border-radius: 10px;
            border-left: 4px solid #667eea;
        }
        
        .stat-value {
            font-size: 2em;
            font-weight: bold;
            color: #667eea;
        }
        
        .stat-label {
            color: #666;
            font-size: 0.9em;
            margin-top: 5px;
        }
        
        .filters {
            background: white;
            border-radius: 15px;
            padding: 20px;
            margin-bottom: 30px;
            box-shadow: 0 5px 15px rgba(0,0,0,0.08);
        }
        
        .filter-buttons {
            display: flex;
            gap: 10px;
            flex-wrap: wrap;
        }
        
        .filter-btn {
            padding: 10px 20px;
            border: 2px solid #e0e0e0;
            background: white;
            border-radius: 25px;
            cursor: pointer;
            transition: all 0.3s;
            font-size: 0.95em;
        }
        
        .filter-btn:hover {
            border-color: #667eea;
            background: #f8f9ff;
        }
        
        .filter-btn.active {
            background: #667eea;
            color: white;
            border-color: #667eea;
        }
        
        .search-box {
            margin-bottom: 15px;
        }
        
        .search-box input {
            width: 100%;
            padding: 12px 20px;
            border: 2px solid #e0e0e0;
            border-radius: 25px;
            font-size: 1em;
            transition: border-color 0.3s;
        }
        
        .search-box input:focus {
            outline: none;
            border-color: #667eea;
        }
        
        .endpoints {
            display: grid;
            gap: 20px;
        }
        
        .endpoint-group {
            background: white;
            border-radius: 15px;
            overflow: hidden;
            box-shadow: 0 5px 15px rgba(0,0,0,0.08);
        }
        
        .group-header {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 20px;
            font-size: 1.3em;
            font-weight: bold;
        }
        
        .endpoint {
            padding: 20px;
            border-bottom: 1px solid #f0f0f0;
            transition: background 0.2s;
        }
        
        .endpoint:hover {
            background: #f8f9ff;
        }
        
        .endpoint:last-child {
            border-bottom: none;
        }
        
        .endpoint-header {
            display: flex;
            align-items: center;
            gap: 15px;
            margin-bottom: 10px;
        }
        
        .method {
            padding: 5px 12px;
            border-radius: 5px;
            font-weight: bold;
            font-size: 0.85em;
            text-transform: uppercase;
        }
        
        .method.GET { background: #61affe; color: white; }
        .method.POST { background: #49cc90; color: white; }
        .method.PUT { background: #fca130; color: white; }
        .method.DELETE { background: #f93e3e; color: white; }
        .method.PATCH { background: #50e3c2; color: white; }
        
        .path {
            font-family: 'Courier New', monospace;
            font-size: 1.1em;
            color: #333;
            flex: 1;
        }
        
        .auth-badge {
            background: #ff6b6b;
            color: white;
            padding: 3px 10px;
            border-radius: 12px;
            font-size: 0.8em;
        }
        
        .description {
            color: #666;
            margin-left: 60px;
            line-height: 1.5;
        }
        
        .parameters {
            margin-left: 60px;
            margin-top: 10px;
        }
        
        .param {
            display: inline-block;
            background: #f0f0f0;
            padding: 5px 10px;
            border-radius: 5px;
            margin-right: 8px;
            margin-top: 5px;
            font-size: 0.9em;
        }
        
        .param-required {
            background: #ffe4e4;
            color: #d00;
        }
        
        .no-endpoints {
            background: white;
            border-radius: 15px;
            padding: 60px;
            text-align: center;
            color: #999;
            font-size: 1.2em;
        }
        
        footer {
            text-align: center;
            color: white;
            margin-top: 50px;
            padding: 20px;
        }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>🚀 CampoSocial API Explorer</h1>
            <p class="subtitle">Interactive API documentation and endpoint explorer</p>
            <div class="stats">
                <div class="stat">
                    <div class="stat-value" id="totalEndpoints">0</div>
                    <div class="stat-label">Total Endpoints</div>
                </div>
                <div class="stat">
                    <div class="stat-value" id="totalGroups">0</div>
                    <div class="stat-label">API Groups</div>
                </div>
                <div class="stat">
                    <div class="stat-value" id="authEndpoints">0</div>
                    <div class="stat-label">Protected Routes</div>
                </div>
            </div>
        </header>
        
        <div class="filters">
            <div class="search-box">
                <input type="text" id="searchInput" placeholder="🔍 Search endpoints..." />
            </div>
            <div class="filter-buttons">
                <button class="filter-btn active" data-filter="all">All</button>
                <button class="filter-btn" data-filter="GET">GET</button>
                <button class="filter-btn" data-filter="POST">POST</button>
                <button class="filter-btn" data-filter="PUT">PUT</button>
                <button class="filter-btn" data-filter="DELETE">DELETE</button>
                <button class="filter-btn" data-filter="auth">🔒 Protected</button>
            </div>
        </div>
        
        <div class="endpoints" id="endpointsContainer">
            <!-- Endpoints will be loaded here -->
        </div>
        
        <footer>
            <p>Made with ❤️ by CampoSocial Team</p>
        </footer>
    </div>
    
    <script>
        let allEndpoints = [];
        
        async function loadEndpoints() {
            try {
                const response = await fetch('/api-explorer/data');
                const data = await response.json();
                allEndpoints = data.endpoints;
                renderEndpoints(allEndpoints);
                updateStats(allEndpoints);
            } catch (error) {
                console.error('Failed to load endpoints:', error);
            }
        }
        
        function updateStats(endpoints) {
            const totalEndpoints = endpoints.reduce((sum, group) => sum + group.endpoints.length, 0);
            const totalGroups = endpoints.length;
            const authEndpoints = endpoints.reduce((sum, group) => 
                sum + group.endpoints.filter(e => e.requires_auth).length, 0);
            
            document.getElementById('totalEndpoints').textContent = totalEndpoints;
            document.getElementById('totalGroups').textContent = totalGroups;
            document.getElementById('authEndpoints').textContent = authEndpoints;
        }
        
        function renderEndpoints(endpoints) {
            const container = document.getElementById('endpointsContainer');
            
            if (endpoints.length === 0) {
                container.innerHTML = '<div class="no-endpoints">No endpoints found</div>';
                return;
            }
            
            container.innerHTML = endpoints.map(group => `
                <div class="endpoint-group">
                    <div class="group-header">${group.name}</div>
                    ${group.endpoints.map(endpoint => `
                        <div class="endpoint" data-method="${endpoint.method}" data-auth="${endpoint.requires_auth}">
                            <div class="endpoint-header">
                                <span class="method ${endpoint.method}">${endpoint.method}</span>
                                <span class="path">${endpoint.path}</span>
                                ${endpoint.requires_auth ? '<span class="auth-badge">🔒 Auth Required</span>' : ''}
                            </div>
                            ${endpoint.description ? `<div class="description">${endpoint.description}</div>` : ''}
                            ${endpoint.parameters && endpoint.parameters.length > 0 ? `
                                <div class="parameters">
                                    ${endpoint.parameters.map(param => 
                                        `<span class="param ${param.required ? 'param-required' : ''}">${param.name}${param.required ? '*' : ''}</span>`
                                    ).join('')}
                                </div>
                            ` : ''}
                        </div>
                    `).join('')}
                </div>
            `).join('');
        }
        
        // Search functionality
        document.getElementById('searchInput').addEventListener('input', (e) => {
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
        });
        
        // Filter buttons
        document.querySelectorAll('.filter-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
                e.target.classList.add('active');
                
                const filter = e.target.dataset.filter;
                
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
