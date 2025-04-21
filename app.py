import os
import sys
import logging
import socket
import hashlib
import traceback
import string
import secrets
from datetime import datetime, timedelta
from functools import wraps
from flask import Flask, request, jsonify, render_template, session, redirect, url_for, flash, send_file
from flask_socketio import SocketIO
from database import init_db, get_db
from models import Admin, Company, Cashier, Customer, QueueHistory
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from io import BytesIO
import csv

# Set up logging
logging.basicConfig(level=logging.DEBUG, 
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    stream=sys.stdout)
logger = logging.getLogger('app')
logger.info("Starting Virtual Queue System")

# Initialize Flask app
app = Flask(__name__)

# Initialize secret key
secret_key = os.getenv('SECRET_KEY')
if not secret_key:
    # Generate a consistent secret key if not provided
    host_id = socket.gethostname() if hasattr(socket, 'gethostname') else 'unknown'
    secret_key = hashlib.sha256(host_id.encode()).hexdigest()
    logger.info(f"Generated SECRET_KEY from hostname: {host_id[:4]}...")

app.config['SECRET_KEY'] = secret_key

# Configure database
def setup_database():
    # Get database configuration from environment variables
    DATABASE_URL = os.getenv('DATABASE_URL')
    if not DATABASE_URL:
        # Fallback to SQLite for local development
        DB_PATH = os.getenv('DB_PATH', '/app/data/queue_system.db')
        db_dir = os.path.dirname(DB_PATH)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir, exist_ok=True)
        DATABASE_URL = f'sqlite:///{DB_PATH}'
        logger.info(f"Using SQLite database at: {DB_PATH}")
    else:
        logger.info("Using PostgreSQL database from DATABASE_URL")
    
    app.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URL
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    
    # Initialize SQLAlchemy
    db = SQLAlchemy(app)
    
    # Initialize Flask-Migrate
    migrate = Migrate(app, db)
    
    # Test database connection
    try:
        with app.app_context():
            db.engine.connect()
            logger.info("Database connection test successful")
            
            # Create all tables
            db.create_all()
            logger.info("Database tables created successfully")
            
            # First-time setup - create default admin if none exists
            admin_count = Admin.query.count()
            if admin_count == 0:
                default_username = os.getenv('DEFAULT_ADMIN_USERNAME', 'admin')
                default_password = os.getenv('DEFAULT_ADMIN_PASSWORD', 'password')
                
                default_admin = Admin(username=default_username)
                default_admin.set_password(default_password)
                db.session.add(default_admin)
                db.session.commit()
                
                logger.info(f"Created default admin with username: {default_username}")
                logger.info(f"IMPORTANT: Please change the default password immediately!")
    except Exception as e:
        logger.error(f"Error setting up database: {e}")
        logger.error(traceback.format_exc())
        raise
    
    return db

# Initialize database
db = setup_database()

# Initialize SocketIO
socketio = SocketIO(app, cors_allowed_origins="*")

# Helper Functions
def generate_company_code():
    letters = string.ascii_uppercase
    return ''.join(secrets.choice(letters) for _ in range(6))

def generate_otp():
    digits = string.digits
    return ''.join(secrets.choice(digits) for _ in range(6))

def calculate_wait_time(cashier_id):
    customers = Customer.query.filter_by(cashier_id=cashier_id, status='waiting').order_by(Customer.position).all()
    history = QueueHistory.query.filter_by(cashier_number=Cashier.query.get(cashier_id).cashier_number)
    
    # Calculate average serving time (default to 3 minutes if not enough data)
    served_customers = history.filter(QueueHistory.wait_time_seconds.isnot(None)).all()
    if len(served_customers) > 5:
        avg_serving_time = sum(c.wait_time_seconds for c in served_customers[-5:]) / 5  # Last 5 customers
    else:
        avg_serving_time = 180  # 3 minutes default
    
    return avg_serving_time

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'admin_id' not in session:
            flash('Please log in first.', 'danger')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# Routes
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/health')
def health():
    return jsonify({"status": "healthy", "database": "PostgreSQL"}), 200

@app.route('/api/health')
def api_health():
    return jsonify({"status": "API is running", "time": str(datetime.utcnow())}), 200

@app.route('/api/db-health')
def db_health():
    try:
        # Try to make a simple query
        admin_count = Admin.query.count()
        company_count = Company.query.count()
        history_count = QueueHistory.query.count()
        
        return jsonify({
            "status": "Database is connected",
            "admin_count": admin_count,
            "company_count": company_count,
            "history_count": history_count,
            "timestamp": datetime.utcnow().isoformat()
        })
    except Exception as e:
        return jsonify({
            "status": "Database error",
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat()
        }), 500

@app.route('/export/<int:company_id>')
@login_required
def export_history(company_id):
    try:
        company = Company.query.get_or_404(company_id)

        if company.admin_id != session.get('admin_id'):
            flash("Unauthorized access", "danger")
            return redirect(url_for('dashboard'))

        # Get all history entries for this company
        history = QueueHistory.query.filter_by(company_id=company_id).order_by(QueueHistory.join_time).all()

        # Create CSV in memory
        output = BytesIO()
        writer = csv.writer(output)
        
        # Write header
        writer.writerow([
            'Cashier Number',
            'OTP',
            'Join Time',
            'Served Time',
            'Wait Time (seconds)',
            'Status',
            'Delays'
        ])

        # Write data rows
        for entry in history:
            writer.writerow([
                entry.cashier_number,
                entry.otp,
                entry.join_time.strftime('%Y-%m-%d %H:%M:%S'),
                entry.served_time.strftime('%Y-%m-%d %H:%M:%S') if entry.served_time else '',
                entry.wait_time_seconds or '',
                entry.status,
                entry.delays
            ])

        # Prepare response
        output.seek(0)
        return (
            output.getvalue(),
            200,
            {
                'Content-Type': 'text/csv',
                'Content-Disposition': f'attachment; filename=queue_history_{company_id}_{datetime.utcnow().strftime("%Y%m%d_%H%M%S")}.csv'
            }
        )
    except Exception as e:
        logger.error(f"Error exporting history: {e}")
        logger.error(traceback.format_exc())
        flash("Error exporting history. Please check logs.", "danger")
        return redirect(url_for('manage_company', company_id=company_id))

# Ensure application variable exists for Gunicorn
application = app

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    logger.info(f"Starting server on port {port}")
    
    try:
        from gevent import pywsgi
        from geventwebsocket.handler import WebSocketHandler
        
        logger.info("Using gevent WebSocket server")
        server = pywsgi.WSGIServer(
            ('0.0.0.0', port), 
            app, 
            handler_class=WebSocketHandler,
            log=logger
        )
        server.serve_forever()
    except Exception as e:
        logger.error(f"Error running the server: {e}")
        logger.error(traceback.format_exc())