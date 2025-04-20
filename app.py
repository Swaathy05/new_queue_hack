# app.py - Main application file using SQLite for reliability

from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session, render_template_string
from flask_sqlalchemy import SQLAlchemy
from flask_socketio import SocketIO, emit
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
import json
import os
import qrcode
from io import BytesIO
import base64
import csv
import secrets
import string
from functools import wraps
import logging
import sys
import traceback

# Set up logging
logging.basicConfig(level=logging.DEBUG, 
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    stream=sys.stdout)
logger = logging.getLogger('app')
logger.info("Starting Virtual Queue System")

# Initialize Flask app
app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'ventic')
logger.info(f"Using SECRET_KEY: {app.config['SECRET_KEY']}")

# Configure SQLite database - use a persistent path for Railway
DB_PATH = os.getenv('DB_PATH', 'queue_system.db')
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{DB_PATH}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
logger.info(f"Database URI: {app.config['SQLALCHEMY_DATABASE_URI']}")

# Initialize extensions
try:
    db = SQLAlchemy(app)
    logger.info("SQLAlchemy initialized")
    
    # Update SocketIO initialization for better compatibility
    socketio = SocketIO(
        app, 
        cors_allowed_origins="*", 
        async_mode='gevent',
        logger=True,
        engineio_logger=True  # Enable more detailed logging
    )
    logger.info("SocketIO initialized with async_mode='gevent'")
except Exception as e:
    logger.error(f"Error initializing extensions: {e}")
    logger.error(traceback.format_exc())

# Error handler for all exceptions
@app.errorhandler(Exception)
def handle_exception(e):
    logger.error(f"Unhandled exception: {str(e)}")
    logger.error(traceback.format_exc())
    return jsonify({"error": "Internal Server Error", "details": str(e)}), 500

# Simple health check that doesn't require database
@app.route('/api/health')
def api_health():
    return jsonify({"status": "API is running", "time": str(datetime.utcnow())}), 200

# Models
class Admin(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    companies = db.relationship('Company', backref='admin', lazy=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Company(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    service_type = db.Column(db.String(100), nullable=False)
    admin_id = db.Column(db.Integer, db.ForeignKey('admin.id'), nullable=False)
    company_code = db.Column(db.String(20), unique=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    cashiers = db.relationship('Cashier', backref='company', lazy=True, cascade="all, delete-orphan")

class Cashier(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey('company.id'), nullable=False)
    cashier_number = db.Column(db.Integer, nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    customers = db.relationship('Customer', backref='cashier', lazy=True)

class Customer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    cashier_id = db.Column(db.Integer, db.ForeignKey('cashier.id'), nullable=False)
    otp = db.Column(db.String(6), nullable=False)
    join_time = db.Column(db.DateTime, default=datetime.utcnow)
    served_time = db.Column(db.DateTime)
    status = db.Column(db.String(20), default='waiting')  # waiting, serving, served, delayed, removed
    delays = db.Column(db.Integer, default=0)
    position = db.Column(db.Integer, nullable=False)
    serving_start_time = db.Column(db.DateTime)

class QueueHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey('company.id'), nullable=False)
    cashier_number = db.Column(db.Integer, nullable=False)
    otp = db.Column(db.String(6), nullable=False)
    join_time = db.Column(db.DateTime, nullable=False)
    served_time = db.Column(db.DateTime)
    wait_time_seconds = db.Column(db.Integer)
    status = db.Column(db.String(20), nullable=False)
    delays = db.Column(db.Integer, default=0)

# Create database tables at startup
with app.app_context():
    try:
        db.create_all()
        logger.info("Database tables created")
    except Exception as e:
        logger.error(f"Error creating database tables: {e}")
        logger.error(traceback.format_exc())

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
    # If user is logged in, redirect to dashboard - but provide alternate navigation
    html = '''
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Virtual Queue System</title>
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0-alpha1/dist/css/bootstrap.min.css" rel="stylesheet">
    </head>
    <body>
        <div class="container mt-5">
            <div class="jumbotron text-center">
                <h1 class="display-4">Welcome to Virtual Queue System</h1>
                <p class="lead">A smart solution for managing customer queues</p>
                <hr class="my-4">
            </div>
            
            <div class="row mt-5">
                <div class="col-md-6 mx-auto">
                    <div class="card">
                        <div class="card-header">
                            <h3>Choose an option</h3>
                        </div>
                        <div class="card-body">
                            <div class="d-grid gap-3">
                                <a href="/login" class="btn btn-primary btn-lg">Login</a>
                                <a href="/register" class="btn btn-success btn-lg">Register</a>
                                <a href="/admin" class="btn btn-info btn-lg">Admin Panel</a>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
        <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0-alpha1/dist/js/bootstrap.bundle.min.js"></script>
    </body>
    </html>
    '''
    return html

@app.route('/health')
def health():
    return jsonify({"status": "healthy", "database": "sqlite"}), 200

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        
        if password != confirm_password:
            flash('Passwords do not match.', 'danger')
            return redirect(url_for('register'))
        
        if Admin.query.filter_by(username=username).first():
            flash('Username already exists.', 'danger')
            return redirect(url_for('register'))
        
        admin = Admin(username=username)
        admin.set_password(password)
        
        db.session.add(admin)
        db.session.commit()
        
        flash('Account created successfully. Please log in.', 'success')
        return redirect(url_for('login'))
    
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        admin = Admin.query.filter_by(username=username).first()
        
        if admin and admin.check_password(password):
            session['admin_id'] = admin.id
            flash('Logged in successfully.', 'success')
            return redirect(url_for('dashboard'))
        
        flash('Invalid username or password.', 'danger')
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('admin_id', None)
    flash('Logged out successfully.', 'success')
    return redirect(url_for('index'))

@app.route('/dashboard')
@login_required
def dashboard():
    admin_id = session.get('admin_id')
    companies = Company.query.filter_by(admin_id=admin_id).all()
    
    # Use a hardcoded template to avoid the create_company URL issue
    html = '''
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Dashboard - Virtual Queue System</title>
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0-alpha1/dist/css/bootstrap.min.css" rel="stylesheet">
    </head>
    <body>
        <div class="container mt-5">
            <div class="d-flex justify-content-between align-items-center mb-4">
                <h1>Admin Dashboard</h1>
                <a href="/create_company" class="btn btn-primary">Create New Company</a>
            </div>
            
            {% if companies %}
            <div class="row">
                {% for company in companies %}
                <div class="col-md-4 mb-4">
                    <div class="card h-100">
                        <div class="card-body">
                            <h5 class="card-title">{{ company.name }}</h5>
                            <p class="card-text text-muted">{{ company.service_type }}</p>
                            <p><strong>Code:</strong> {{ company.company_code }}</p>
                            <p><strong>Created:</strong> {{ company.created_at.strftime('%Y-%m-%d') }}</p>
                            <p><strong>Cashiers:</strong> {{ company.cashiers|length }}</p>
                        </div>
                        <div class="card-footer bg-white border-top-0">
                            <a href="/manage_company/{{ company.id }}" class="btn btn-primary w-100">Manage</a>
                        </div>
                    </div>
                </div>
                {% endfor %}
            </div>
            {% else %}
            <div class="alert alert-info">
                <p>You don't have any companies yet. Click the "Create New Company" button to get started.</p>
            </div>
            {% endif %}
        </div>
        <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0-alpha1/dist/js/bootstrap.bundle.min.js"></script>
    </body>
    </html>
    '''
    
    # Render the hardcoded template with the companies data
    return render_template_string(html, companies=companies)

@app.route('/create_company', methods=['GET', 'POST'])
@login_required
def create_company():
    if request.method == 'POST':
        name = request.form.get('name')
        service_type = request.form.get('service_type')
        num_cashiers = int(request.form.get('num_cashiers'))
        
        # Generate unique company code
        while True:
            company_code = generate_company_code()
            if not Company.query.filter_by(company_code=company_code).first():
                break
        
        # Create company
        company = Company(
            name=name,
            service_type=service_type,
            admin_id=session.get('admin_id'),
            company_code=company_code
        )
        
        db.session.add(company)
        db.session.flush()  # Get company ID without committing
        
        # Create cashiers
        for i in range(1, num_cashiers + 1):
            cashier = Cashier(
                company_id=company.id,
                cashier_number=i,
                is_active=True
            )
            db.session.add(cashier)
        
        db.session.commit()
        
        flash('Company created successfully.', 'success')
        return redirect(url_for('manage_company', company_id=company.id))
    
    return render_template('create_company.html')

@app.route('/manage_company/<int:company_id>')
@login_required
def manage_company(company_id):
    company = Company.query.get_or_404(company_id)
    
    # Check if admin owns this company
    if company.admin_id != int(session.get('admin_id')):
        flash('Unauthorized access.', 'danger')
        return redirect(url_for('dashboard'))
    
    cashiers = Cashier.query.filter_by(company_id=company_id).order_by(Cashier.cashier_number).all()
    
    # Get queue stats
    stats = {
        'total_served': QueueHistory.query.filter_by(company_id=company_id, status='served').count(),
        'total_delayed': QueueHistory.query.filter_by(company_id=company_id).filter(QueueHistory.delays > 0).count(),
        'avg_wait_time': 0
    }
    
    served_customers = QueueHistory.query.filter_by(company_id=company_id, status='served').all()
    if served_customers:
        total_wait_time = sum(c.wait_time_seconds or 0 for c in served_customers)
        stats['avg_wait_time'] = total_wait_time / len(served_customers) if len(served_customers) > 0 else 0
    
    # Generate QR code
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(f"{request.host_url}join/{company.company_code}")
    qr.make(fit=True)
    
    img = qr.make_image(fill_color="black", back_color="white")
    buffered = BytesIO()
    img.save(buffered)
    qr_code = base64.b64encode(buffered.getvalue()).decode('utf-8')
    
    return render_template('manage_company.html', company=company, cashiers=cashiers, stats=stats, qr_code=qr_code)
@app.route('/export/<int:company_id>')
@login_required
def export_history(company_id):
    company = Company.query.get_or_404(company_id)

    if company.admin_id != session.get('admin_id'):
        flash("Unauthorized access", "danger")
        return redirect(url_for('dashboard'))

    history = QueueHistory.query.filter_by(company_id=company_id).all()

    output = BytesIO()
    writer = csv.writer(output)
    writer.writerow(['Cashier Number', 'OTP', 'Join Time', 'Served Time', 'Wait Time (s)', 'Status', 'Delays'])

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

    output.seek(0)
    return (
        output.getvalue(),
        200,
        {
            'Content-Type': 'text/csv',
            'Content-Disposition': f'attachment; filename=queue_history_{company_id}.csv'
        }
    )

@app.route('/api/get_cashier_queue/<int:cashier_id>')
@login_required
def get_cashier_queue(cashier_id):
    try:
        # Check if cashier exists
        cashier = Cashier.query.get(cashier_id)
        if not cashier:
            logger.warning(f"Cashier with ID {cashier_id} not found")
            return jsonify({
                'error': 'Cashier not found',
                'cashier_number': None,
                'is_active': False,
                'queue': []
            }), 404
        
        # Check if admin owns this company
        company = Company.query.get(cashier.company_id)
        if not company or company.admin_id != int(session.get('admin_id')):
            logger.warning(f"Unauthorized access to cashier {cashier_id}")
            return jsonify({'error': 'Unauthorized access'}), 403
        
        customers = Customer.query.filter_by(cashier_id=cashier_id).order_by(Customer.position).all()
        
        queue_data = []
        for customer in customers:
            # Calculate estimated wait time
            position = customer.position
            estimated_wait_time = int(position * calculate_wait_time(cashier_id))
            
            queue_data.append({
                'id': customer.id,
                'otp': customer.otp,
                'position': position,
                'status': customer.status,
                'delays': customer.delays,
                'join_time': customer.join_time.strftime('%H:%M:%S'),
                'estimated_wait_time': estimated_wait_time,
                'serving_start_time': customer.serving_start_time.strftime('%H:%M:%S') if customer.serving_start_time else None
            })
        
        return jsonify({
            'cashier_number': cashier.cashier_number,
            'is_active': cashier.is_active,
            'queue': queue_data
        })
    except Exception as e:
        logger.error(f"Error in get_cashier_queue: {str(e)}")
        return jsonify({
            'error': 'An error occurred while fetching queue data',
            'cashier_number': None,
            'is_active': False,
            'queue': []
        }), 500

@app.route('/api/toggle_cashier/<int:cashier_id>', methods=['POST'])
@login_required
def toggle_cashier(cashier_id):
    cashier = Cashier.query.get_or_404(cashier_id)
    
    # Check if admin owns this company
    company = Company.query.get(cashier.company_id)
    if company.admin_id != int(session.get('admin_id')):
        return jsonify({'error': 'Unauthorized access'}), 403
    
    # Toggle cashier active status
    cashier.is_active = not cashier.is_active
    db.session.commit()
    
    # Emit socket event to notify all clients
    socketio.emit('cashier_status_change', {
        'cashier_id': cashier_id,
        'is_active': cashier.is_active,
        'company_code': company.company_code
    })
    
    return jsonify({'success': True, 'is_active': cashier.is_active})

@app.route('/queue_status/<otp>')
def queue_status(otp):
    customer = Customer.query.filter_by(otp=otp).first_or_404()
    cashier = Cashier.query.get(customer.cashier_id)
    company = Company.query.get(cashier.company_id)
    
    # Calculate estimated wait time
    estimated_wait_seconds = customer.position * calculate_wait_time(cashier.id)
    
    response = app.make_response(render_template(
        'queue_status.html',
        customer=customer,
        cashier=cashier,
        company=company,
        estimated_wait_seconds=estimated_wait_seconds
    ))
    
    # Set cache headers 
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    
    return response

@app.route('/api/check_status/<otp>')
def check_status(otp):
    try:
        customer = Customer.query.filter_by(otp=otp).first_or_404()
        cashier = Cashier.query.get(customer.cashier_id)
        company = Company.query.get(cashier.company_id)
        
        # Calculate estimated wait time
        estimated_wait_seconds = customer.position * calculate_wait_time(cashier.id)
        
        # Calculate time since serving started (if applicable)
        serving_time_passed = None
        if customer.serving_start_time:
            serving_time_passed = (datetime.utcnow() - customer.serving_start_time).total_seconds()
        
        response = jsonify({
            'position': customer.position,
            'status': customer.status,
            'cashier_number': cashier.cashier_number,
            'cashier_is_active': cashier.is_active,
            'estimated_wait_seconds': estimated_wait_seconds,
            'serving_time_passed': serving_time_passed,
            'delays': customer.delays,
            'company_code': company.company_code,
            'last_update_time': datetime.utcnow().isoformat(),
            'join_time': customer.join_time.isoformat() if customer.join_time else None,
            'served_time': customer.served_time.isoformat() if customer.served_time else None
        })
        
        # Set cache headers
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
        
        return response
    except Exception as e:
        logger.error(f"Error checking status for OTP {otp}: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({'error': 'Could not retrieve status information'}), 500

@app.route('/join/<company_code>')
def join_queue_page(company_code):
    company = Company.query.filter_by(company_code=company_code).first_or_404()
    cashiers = Cashier.query.filter_by(company_id=company.id, is_active=True).all()
    
    return render_template('join_queue.html', company=company, cashiers=cashiers)

@app.route('/api/join_queue/<company_code>', methods=['POST'])
def join_queue(company_code):
    company = Company.query.filter_by(company_code=company_code).first_or_404()
    
    # Find the cashier with the shortest queue
    cashiers = Cashier.query.filter_by(company_id=company.id, is_active=True).all()
    
    if not cashiers:
        return jsonify({'error': 'No active cashiers available'}), 400
    
    shortest_queue_cashier = None
    min_queue_length = float('inf')
    
    for cashier in cashiers:
        queue_length = Customer.query.filter_by(
            cashier_id=cashier.id, 
            status='waiting'
        ).count()
        
        if queue_length < min_queue_length:
            min_queue_length = queue_length
            shortest_queue_cashier = cashier
    
    # Generate OTP
    while True:
        otp = generate_otp()
        if not Customer.query.filter_by(otp=otp).first():
            break
    
    # Calculate position
    position = min_queue_length + 1
    
    # Verify no position conflicts
    existing_position = Customer.query.filter_by(
        cashier_id=shortest_queue_cashier.id,
        position=position
    ).first()
    
    if existing_position:
        # Fix position sequence before adding new customer
        logger.warning(f"Position conflict detected at position {position} for cashier {shortest_queue_cashier.id}. Fixing positions.")
        customers_to_reorder = Customer.query.filter_by(
            cashier_id=shortest_queue_cashier.id,
            status='waiting'
        ).order_by(Customer.join_time).all()
        
        # Reorder all waiting customers by join time
        for i, cust in enumerate(customers_to_reorder, 1):
            cust.position = i
        
        db.session.commit()
        
        # Recalculate position after fixing
        position = Customer.query.filter_by(
            cashier_id=shortest_queue_cashier.id, 
            status='waiting'
        ).count() + 1
    
    # Create customer in queue
    customer = Customer(
        cashier_id=shortest_queue_cashier.id,
        otp=otp,
        position=position,
        status='waiting'  # Explicitly set status to waiting
    )
    
    db.session.add(customer)
    
    # Check if any other customers are incorrectly marked as serving
    serving_customers = Customer.query.filter_by(
        cashier_id=shortest_queue_cashier.id,
        status='serving'
    ).all()
    
    if len(serving_customers) > 1:
        # More than one customer is marked as serving - fix this issue
        logger.warning(f"Multiple serving customers detected for cashier {shortest_queue_cashier.id}. Found {len(serving_customers)} serving customers.")
        
        # Sort by join time to keep the oldest one as serving
        serving_customers.sort(key=lambda x: x.join_time)
        
        # Mark all except the first one as waiting
        for i, cust in enumerate(serving_customers):
            if i > 0:  # Skip the first (oldest) one
                logger.info(f"Fixing customer {cust.otp} status from 'serving' to 'waiting'")
                cust.status = 'waiting'
                cust.serving_start_time = None
                
                # Ensure no duplicate positions
                if cust.position == 1:
                    # Find highest position number
                    max_position = db.session.query(db.func.max(Customer.position)).filter(
                        Customer.cashier_id == shortest_queue_cashier.id,
                        Customer.status == 'waiting'
                    ).scalar() or 1
                    
                    cust.position = max_position + 1
                    logger.info(f"Fixed position for customer {cust.otp} from 1 to {cust.position}")
    
    # If this is the first customer for this cashier, mark as serving
    if position == 1 and not serving_customers:
        customer.status = 'serving'
        customer.serving_start_time = datetime.utcnow()
        
        # Emit socket event to notify the customer
        socketio.emit('customer_turn', {
            'otp': customer.otp,
            'cashier_number': shortest_queue_cashier.cashier_number,
            'company_code': company.company_code
        })
    
    # Final commit to save all changes
    db.session.commit()
    
    # Calculate estimated wait time
    estimated_wait_seconds = position * calculate_wait_time(shortest_queue_cashier.id)
    
    return jsonify({
        'success': True,
        'otp': otp,
        'position': position,
        'status': customer.status,  # Include status in response
        'cashier_number': shortest_queue_cashier.cashier_number,
        'estimated_wait_seconds': estimated_wait_seconds
    })

# Add a standalone admin panel route
@app.route('/admin')
def admin_panel():
    html = '''
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Admin Panel - Virtual Queue</title>
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0-alpha1/dist/css/bootstrap.min.css" rel="stylesheet">
    </head>
    <body>
        <div class="container mt-5">
            <div class="row">
                <div class="col-12 mb-4">
                    <h1>Virtual Queue Admin Panel</h1>
                    <div class="alert alert-success">
                        This is a standalone page that doesn't depend on other routes
                    </div>
                </div>
                
                <div class="col-md-6">
                    <div class="card mb-4">
                        <div class="card-header">
                            Authentication
                        </div>
                        <div class="card-body">
                            <div class="list-group">
                                <a href="/login" class="list-group-item list-group-item-action">Login</a>
                                <a href="/register" class="list-group-item list-group-item-action">Register</a>
                                <a href="/logout" class="list-group-item list-group-item-action">Logout</a>
                            </div>
                        </div>
                    </div>
                </div>
                
                <div class="col-md-6">
                    <div class="card mb-4">
                        <div class="card-header">
                            Test Pages
                        </div>
                        <div class="card-body">
                            <div class="list-group">
                                <a href="/api/health" class="list-group-item list-group-item-action">API Health</a>
                                <a href="/test" class="list-group-item list-group-item-action">Test Endpoint</a>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
        <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0-alpha1/dist/js/bootstrap.bundle.min.js"></script>
    </body>
    </html>
    '''
    return html

# Basic route for testing
@app.route('/test')
def test():
    return jsonify({"message": "Test endpoint working!", "environment": dict(os.environ)}), 200

# Function to update positions for customers in a queue
def update_customer_positions(cashier_id, start_position):
    try:
        # Add transactions for safety
        customers_to_update = Customer.query.filter_by(
            cashier_id=cashier_id, 
            status='waiting'
        ).filter(Customer.position > start_position).order_by(Customer.position).all()
        
        for customer in customers_to_update:
            old_position = customer.position
            customer.position -= 1
            logger.info(f"Updated customer {customer.otp} position from {old_position} to {customer.position}")
        
        db.session.commit()
        
        # Emit more detailed data for debugging
        socketio.emit('queue_updated', {
            'cashier_id': cashier_id, 
            'updated_count': len(customers_to_update),
            'timestamp': datetime.utcnow().isoformat()
        })
        
        return customers_to_update
    except Exception as e:
        logger.error(f"Error updating positions: {str(e)}")
        db.session.rollback()  # Important to roll back on error
        return []

@app.route('/api/serve_customer/<int:cashier_id>', methods=['POST'])
def serve_customer(cashier_id):
    try:
        cashier = Cashier.query.get_or_404(cashier_id)
        
        # Handle currently serving customers first
        already_serving = Customer.query.filter_by(cashier_id=cashier_id, status='serving').all()
        
        for customer in already_serving:
            customer.status = 'served'
            customer.served_time = datetime.utcnow()
            
            # Add to history - consider moving this to a function
            wait_time_seconds = int((customer.served_time - customer.join_time).total_seconds())
            history = QueueHistory(
                company_id=cashier.company_id,
                cashier_number=cashier.cashier_number,
                otp=customer.otp,
                join_time=customer.join_time,
                served_time=customer.served_time,
                wait_time_seconds=wait_time_seconds,
                status='served',
                delays=customer.delays
            )
            db.session.add(history)
        
        # Process next customer
        next_customer = Customer.query.filter_by(
            cashier_id=cashier_id,
            status='waiting'
        ).order_by(Customer.position).first()
        
        if not next_customer:
            db.session.commit()  # Commit changes to already serving customers
            return jsonify({'message': 'No customers waiting in queue'}), 200
        
        # Update next customer
        next_customer.status = 'serving'
        next_customer.serving_start_time = datetime.utcnow()
        old_position = next_customer.position
        
        # Update positions if needed
        if old_position > 1:
            update_customer_positions(cashier_id, 1)  # Update from position 1
        
        db.session.commit()
        
        # Emit events
        socketio.emit('customer_turn', {
            'otp': next_customer.otp,
            'cashier_number': cashier.cashier_number,
            'company_code': cashier.company.company_code
        })
        
        return jsonify({
            'message': 'Customer now being served',
            'otp': next_customer.otp
        }), 200
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error serving customer: {str(e)}")
        return jsonify({'error': 'An error occurred while serving customer'}), 500

@app.route('/api/remove_customer/<int:customer_id>', methods=['POST'])
@login_required
def remove_customer(customer_id):
    customer = Customer.query.get_or_404(customer_id)
    cashier = Cashier.query.get(customer.cashier_id)
    
    # Check if admin owns this company
    company = Company.query.get(cashier.company_id)
    if company.admin_id != int(session.get('admin_id')):
        return jsonify({'error': 'Unauthorized access'}), 403
    
    # Record in history before removing
    history_entry = QueueHistory(
        company_id=company.id,
        cashier_number=cashier.cashier_number,
        otp=customer.otp,
        join_time=customer.join_time,
        served_time=datetime.utcnow(),
        wait_time_seconds=int((datetime.utcnow() - customer.join_time).total_seconds()),
        status='removed',
        delays=customer.delays
    )
    db.session.add(history_entry)
    
    # Store position before updating customer
    old_position = customer.position
    logger.info(f"Removing customer {customer.otp} with position {old_position}")
    was_serving = customer.status == 'serving'
    
    # Update customer status
    customer.status = 'removed'
    
    # Commit the status change
    db.session.commit()
    
    # Update positions for waiting customers behind this one
    updated_customers = update_customer_positions(customer.cashier_id, old_position)
    logger.info(f"Updated positions for {len(updated_customers)} customers")
    
    # If the removed customer was being served, start serving the next customer
    if was_serving:
        next_customer = Customer.query.filter_by(
            cashier_id=cashier.id,
            status='waiting',
            position=1
        ).first()
        
        if next_customer:
            logger.info(f"Marking next customer {next_customer.otp} as serving")
            next_customer.status = 'serving'
            next_customer.serving_start_time = datetime.utcnow()
            db.session.commit()
            
            # Emit socket event to notify the next customer
            socketio.emit('customer_turn', {
                'otp': next_customer.otp,
                'cashier_number': cashier.cashier_number,
                'company_code': company.company_code
            })
    
    # Also emit an event to the removed customer
    socketio.emit('customer_removed', {
        'otp': customer.otp,
        'cashier_number': cashier.cashier_number,
        'company_code': company.company_code
    })
    
    return jsonify({'success': True, 'message': 'Customer removed from queue'})

@app.route('/api/delay_customer/<int:customer_id>', methods=['POST'])
@login_required
def delay_customer(customer_id):
    customer = Customer.query.get_or_404(customer_id)
    cashier = Cashier.query.get(customer.cashier_id)
    
    # Check if admin owns this company
    company = Company.query.get(cashier.company_id)
    if company.admin_id != int(session.get('admin_id')):
        return jsonify({'error': 'Unauthorized access'}), 403
    
    # Only allow delaying customers who are currently serving
    if customer.status != 'serving':
        return jsonify({'error': 'Only currently serving customers can be delayed'}), 400
    
    # Store the current position
    old_position = customer.position
    
    # Update customer status and increment delay count
    customer.status = 'waiting'
    customer.delays += 1
    customer.serving_start_time = None
    
    # Move the delayed customer to the end of the waiting queue
    max_position = db.session.query(db.func.max(Customer.position)).filter(
        Customer.cashier_id == cashier.id,
        Customer.status == 'waiting'
    ).scalar() or 0
    
    # If there are other waiting customers, position this one at the end
    if max_position > 0:
        customer.position = max_position + 1
    
    db.session.commit()
    
    # Emit socket event to notify all clients
    socketio.emit('customer_delayed', {
        'otp': customer.otp,
        'cashier_number': cashier.cashier_number,
        'company_code': company.company_code
    })
    
    # Find the next waiting customer for this cashier
    next_customer = Customer.query.filter_by(
        cashier_id=cashier.id,
        status='waiting',
        position=1
    ).first()
    
    # If there's a next customer, mark them as serving
    if next_customer:
        next_customer.status = 'serving'
        next_customer.serving_start_time = datetime.utcnow()
        db.session.commit()
        
        # Emit socket event to notify the next customer
        socketio.emit('customer_turn', {
            'otp': next_customer.otp,
            'cashier_number': cashier.cashier_number,
            'company_code': company.company_code
        })
    
    return jsonify({'success': True, 'message': 'Customer delayed'})

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
