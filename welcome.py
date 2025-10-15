from flask import Blueprint, render_template_string

welcome_bp = Blueprint('welcome', __name__)

WELCOME_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>CampoSocial API - Welcome</title>
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
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 20px;
        }
        
        .container {
            background: white;
            border-radius: 20px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.2);
            max-width: 900px;
            width: 100%;
            overflow: hidden;
        }
        
        .header {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 40px;
            text-align: center;
        }
        
        .logo {
            font-size: 3em;
            margin-bottom: 10px;
        }
        
        h1 {
            font-size: 2.5em;
            margin-bottom: 10px;
            font-weight: 700;
        }
        
        .subtitle {
            font-size: 1.2em;
            opacity: 0.95;
        }
        
        .version-badge {
            display: inline-block;
            background: rgba(255,255,255,0.2);
            padding: 5px 15px;
            border-radius: 20px;
            margin-top: 15px;
            font-size: 0.9em;
        }
        
        .content {
            padding: 40px;
        }
        
        .section {
            margin-bottom: 35px;
        }
        
        .section-title {
            font-size: 1.5em;
            color: #333;
            margin-bottom: 20px;
            display: flex;
            align-items: center;
            gap: 10px;
        }
        
        .cards {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }
        
        .card {
            background: #f8f9fa;
            border-radius: 12px;
            padding: 25px;
            text-decoration: none;
            color: #333;
            transition: all 0.3s ease;
            border: 2px solid transparent;
            display: flex;
            flex-direction: column;
            align-items: center;
            text-align: center;
        }
        
        .card:hover {
            transform: translateY(-5px);
            box-shadow: 0 10px 25px rgba(0,0,0,0.1);
            border-color: #667eea;
        }
        
        .card-icon {
            font-size: 2.5em;
            margin-bottom: 15px;
        }
        
        .card-title {
            font-size: 1.3em;
            font-weight: 600;
            margin-bottom: 10px;
            color: #667eea;
        }
        
        .card-description {
            font-size: 0.95em;
            color: #666;
            line-height: 1.5;
        }
        
        .endpoints-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
        }
        
        .endpoint-item {
            background: white;
            border: 2px solid #e0e0e0;
            border-radius: 10px;
            padding: 15px;
            transition: all 0.3s ease;
        }
        
        .endpoint-item:hover {
            border-color: #667eea;
            background: #f8f9ff;
        }
        
        .endpoint-name {
            font-weight: 600;
            color: #333;
            margin-bottom: 5px;
        }
        
        .endpoint-path {
            font-family: 'Courier New', monospace;
            font-size: 0.85em;
            color: #667eea;
        }
        
        .status-section {
            background: #e8f5e9;
            border-radius: 12px;
            padding: 20px;
            display: flex;
            align-items: center;
            gap: 15px;
        }
        
        .status-indicator {
            width: 12px;
            height: 12px;
            background: #4caf50;
            border-radius: 50%;
            animation: pulse 2s infinite;
        }
        
        @keyframes pulse {
            0% {
                box-shadow: 0 0 0 0 rgba(76, 175, 80, 0.7);
            }
            70% {
                box-shadow: 0 0 0 10px rgba(76, 175, 80, 0);
            }
            100% {
                box-shadow: 0 0 0 0 rgba(76, 175, 80, 0);
            }
        }
        
        .status-text {
            flex: 1;
        }
        
        .status-title {
            font-weight: 600;
            color: #2e7d32;
            margin-bottom: 3px;
        }
        
        .status-message {
            color: #555;
            font-size: 0.9em;
        }
        
        .footer {
            background: #f8f9fa;
            padding: 30px;
            text-align: center;
            border-top: 1px solid #e0e0e0;
        }
        
        .footer-links {
            display: flex;
            justify-content: center;
            gap: 30px;
            margin-bottom: 20px;
        }
        
        .footer-link {
            color: #667eea;
            text-decoration: none;
            font-weight: 500;
            transition: color 0.3s ease;
        }
        
        .footer-link:hover {
            color: #764ba2;
        }
        
        .copyright {
            color: #999;
            font-size: 0.9em;
        }
        
        @media (max-width: 768px) {
            h1 {
                font-size: 2em;
            }
            
            .cards {
                grid-template-columns: 1fr;
            }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div class="logo">🚀</div>
            <h1>CampoSocial API</h1>
            <p class="subtitle">Your Campus Social Network Platform</p>
            <span class="version-badge">Version 1.0</span>
        </div>
        
        <div class="content">
            <div class="section">
                <h2 class="section-title">
                    📚 API Documentation
                </h2>
                <div class="cards">
                    <a href="/docs" class="card">
                        <div class="card-icon">📖</div>
                        <div class="card-title">Swagger UI</div>
                        <div class="card-description">
                            Interactive API documentation with try-it-out functionality
                        </div>
                    </a>
                    <a href="/api-explorer" class="card">
                        <div class="card-icon">🔍</div>
                        <div class="card-title">API Explorer</div>
                        <div class="card-description">
                            Visual endpoint explorer with filtering and search
                        </div>
                    </a>
                    <a href="/camposocial/api/" class="card">
                        <div class="card-icon">🔗</div>
                        <div class="card-title">API Root</div>
                        <div class="card-description">
                            JSON response with all available endpoints
                        </div>
                    </a>
                </div>
            </div>
            
            <div class="section">
                <h2 class="section-title">
                    🛠️ Available Endpoints
                </h2>
                <div class="endpoints-grid">
                    <div class="endpoint-item">
                        <div class="endpoint-name">🔐 Authentication</div>
                        <div class="endpoint-path">/camposocial/api/login</div>
                    </div>
                    <div class="endpoint-item">
                        <div class="endpoint-name">👤 Users</div>
                        <div class="endpoint-path">/camposocial/api/users</div>
                    </div>
                    <div class="endpoint-item">
                        <div class="endpoint-name">📅 Events</div>
                        <div class="endpoint-path">/camposocial/api/events</div>
                    </div>
                    <div class="endpoint-item">
                        <div class="endpoint-name">🛍️ Marketplace</div>
                        <div class="endpoint-path">/camposocial/api/products</div>
                    </div>
                    <div class="endpoint-item">
                        <div class="endpoint-name">💬 Yaps</div>
                        <div class="endpoint-path">/camposocial/api/yaps</div>
                    </div>
                    <div class="endpoint-item">
                        <div class="endpoint-name">👥 Friends</div>
                        <div class="endpoint-path">/camposocial/api/friends</div>
                    </div>
                </div>
            </div>
            
            <div class="section">
                <div class="status-section">
                    <div class="status-indicator"></div>
                    <div class="status-text">
                        <div class="status-title">API Status: Active</div>
                        <div class="status-message">All systems operational</div>
                    </div>
                </div>
            </div>
        </div>
        
        <div class="footer">
            <div class="footer-links">
                <a href="/docs" class="footer-link">Documentation</a>
                <a href="/api-explorer" class="footer-link">Explorer</a>
                <a href="mailto:support@camposocial.app" class="footer-link">Support</a>
            </div>
            <div class="copyright">
                Made with ❤️ by CampoSocial Team
            </div>
        </div>
    </div>
</body>
</html>
"""

@welcome_bp.route('/')
def welcome():
    """Display welcome page with links to API documentation"""
    return render_template_string(WELCOME_HTML)

@welcome_bp.route('/welcome')
def welcome_alt():
    """Alternative welcome page route"""
    return render_template_string(WELCOME_HTML)
