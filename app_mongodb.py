# app_mongodb.py - MongoDB Version of Main Application

from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
from flask_pymongo import PyMongo
from flask_socketio import SocketIO, emit
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
from bson.objectid import ObjectId
import json
import os
import qrcode
from io import BytesIO
import base64
import csv
import secrets
import string
from functools import wraps

# Initialize Flask app
app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'your_secret_key_here')

# Configure MongoDB
mongodb_uri = os.getenv('MONGODB_URI', 'mongodb://localhost:27017/virtual_queue')
app.config['MONGO_URI'] = mongodb_uri

# Initialize extensions
mongo = PyMongo(app)
socketio = SocketIO(app, cors_allowed_origins="*")

# Initialize database collections (equivalent to models)
db = mongo.db

# Ensure indexes for queries
with app.app_context():
    # Create unique index for username in admins collection
    db.admins.create_index('username', unique=True)
    # Create unique index for company_code in companies collection
    db.companies.create_index('company_code', unique=True)
    # Create index for otp in customers collection
    db.customers.create_index('otp', unique=True)
    print("MongoDB indexes created")

# Helper Functions
def generate_company_code():
    letters = string.ascii_uppercase
    return ''.join(secrets.choice(letters) for _ in range(6))

def generate_otp():
    digits = string.digits
    return ''.join(secrets.choice(digits) for _ in range(6))

def calculate_wait_time(cashier_id):
    customers = list(db.customers.find({'cashier_id': cashier_id, 'status': 'waiting'}).sort('position', 1))
    
    # Calculate average serving time (default to 3 minutes if not enough data)
    served_customers = list(db.queue_history.find({'cashier_id': cashier_id, 'wait_time_seconds': {'$exists': True}}))
    
    if len(served_customers) > 5:
        # Get last 5 customers
        recent_customers = served_customers[-5:]
        avg_serving_time = sum(c.get('wait_time_seconds', 0) for c in recent_customers) / 5
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
    if 'admin_id' in session:
        return redirect(url_for('dashboard'))
    return render_template('index.html')

@app.route('/health')
def health():
    return jsonify({"status": "healthy"}), 200

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        
        if password != confirm_password:
            flash('Passwords do not match.', 'danger')
            return redirect(url_for('register'))
        
        # Check if username exists
        if db.admins.find_one({'username': username}):
            flash('Username already exists.', 'danger')
            return redirect(url_for('register'))
        
        # Create new admin
        admin_id = db.admins.insert_one({
            'username': username,
            'password_hash': generate_password_hash(password),
            'created_at': datetime.utcnow()
        }).inserted_id
        
        flash('Account created successfully. Please log in.', 'success')
        return redirect(url_for('login'))
    
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        admin = db.admins.find_one({'username': username})
        
        if admin and check_password_hash(admin['password_hash'], password):
            session['admin_id'] = str(admin['_id'])
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
    companies = list(db.companies.find({'admin_id': admin_id}))
    return render_template('dashboard.html', companies=companies)

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
            if not db.companies.find_one({'company_code': company_code}):
                break
        
        # Create company
        company_id = db.companies.insert_one({
            'name': name,
            'service_type': service_type,
            'admin_id': session.get('admin_id'),
            'company_code': company_code,
            'created_at': datetime.utcnow()
        }).inserted_id
        
        # Create cashiers
        for i in range(1, num_cashiers + 1):
            db.cashiers.insert_one({
                'company_id': str(company_id),
                'cashier_number': i,
                'is_active': True
            })
        
        flash('Company created successfully.', 'success')
        return redirect(url_for('manage_company', company_id=str(company_id)))
    
    return render_template('create_company.html')

@app.route('/manage_company/<company_id>')
@login_required
def manage_company(company_id):
    company = db.companies.find_one({'_id': ObjectId(company_id)})
    
    # Check if admin owns this company
    if company['admin_id'] != session.get('admin_id'):
        flash('Unauthorized access.', 'danger')
        return redirect(url_for('dashboard'))
    
    cashiers = list(db.cashiers.find({'company_id': company_id}).sort('cashier_number', 1))
    
    # Get queue stats
    stats = {
        'total_served': db.queue_history.count_documents({'company_id': company_id, 'status': 'served'}),
        'total_delayed': db.queue_history.count_documents({'company_id': company_id, 'delays': {'$gt': 0}}),
        'avg_wait_time': 0
    }
    
    served_customers = list(db.queue_history.find({'company_id': company_id, 'status': 'served'}))
    if served_customers:
        total_wait_time = sum(c.get('wait_time_seconds', 0) for c in served_customers)
        stats['avg_wait_time'] = total_wait_time / len(served_customers) if len(served_customers) > 0 else 0
    
    # Generate QR code
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(f"{request.host_url}join/{company['company_code']}")
    qr.make(fit=True)
    
    img = qr.make_image(fill_color="black", back_color="white")
    buffered = BytesIO()
    img.save(buffered)
    qr_code = base64.b64encode(buffered.getvalue()).decode('utf-8')
    
    return render_template('manage_company.html', company=company, cashiers=cashiers, stats=stats, qr_code=qr_code)

@app.route('/api/get_cashier_queue/<cashier_id>')
@login_required
def get_cashier_queue(cashier_id):
    cashier = db.cashiers.find_one({'_id': ObjectId(cashier_id)})
    if not cashier:
        return jsonify({'error': 'Cashier not found'}), 404
    
    # Check if admin owns this company
    company = db.companies.find_one({'_id': ObjectId(cashier['company_id'])})
    if company['admin_id'] != session.get('admin_id'):
        return jsonify({'error': 'Unauthorized access'}), 403
    
    customers = list(db.customers.find({'cashier_id': cashier_id}).sort('position', 1))
    
    queue_data = []
    for customer in customers:
        # Calculate estimated wait time
        position = customer['position']
        estimated_wait_time = int(position * calculate_wait_time(cashier_id))
        
        queue_data.append({
            'id': str(customer['_id']),
            'otp': customer['otp'],
            'position': position,
            'status': customer['status'],
            'delays': customer.get('delays', 0),
            'join_time': customer['join_time'].strftime('%H:%M:%S'),
            'estimated_wait_time': estimated_wait_time,
            'serving_start_time': customer.get('serving_start_time', '').strftime('%H:%M:%S') if customer.get('serving_start_time') else None
        })
    
    return jsonify({
        'cashier_number': cashier['cashier_number'],
        'is_active': cashier['is_active'],
        'queue': queue_data
    })

# Add the rest of your routes with MongoDB implementation...

@app.route('/api/toggle_cashier/<cashier_id>', methods=['POST'])
@login_required
def toggle_cashier(cashier_id):
    cashier = db.cashiers.find_one({'_id': ObjectId(cashier_id)})
    if not cashier:
        return jsonify({'error': 'Cashier not found'}), 404
    
    # Check if admin owns this company
    company = db.companies.find_one({'_id': ObjectId(cashier['company_id'])})
    if company['admin_id'] != session.get('admin_id'):
        return jsonify({'error': 'Unauthorized access'}), 403
    
    # Toggle cashier active status
    new_status = not cashier['is_active']
    db.cashiers.update_one(
        {'_id': ObjectId(cashier_id)},
        {'$set': {'is_active': new_status}}
    )
    
    # Emit socket event to notify all clients
    socketio.emit('cashier_status_change', {
        'cashier_id': str(cashier_id),
        'is_active': new_status,
        'company_code': company['company_code']
    })
    
    return jsonify({'success': True, 'is_active': new_status})

@app.route('/queue_status/<otp>')
def queue_status(otp):
    customer = db.customers.find_one({'otp': otp})
    if not customer:
        return render_template('error.html', message='Queue number not found'), 404
    
    cashier = db.cashiers.find_one({'_id': ObjectId(customer['cashier_id'])})
    company = db.companies.find_one({'_id': ObjectId(cashier['company_id'])})
    
    # Calculate estimated wait time
    estimated_wait_seconds = customer['position'] * calculate_wait_time(customer['cashier_id'])
    
    return render_template(
        'queue_status.html',
        customer=customer,
        cashier=cashier,
        company=company,
        estimated_wait_seconds=estimated_wait_seconds
    )

@app.route('/api/check_status/<otp>')
def check_status(otp):
    customer = db.customers.find_one({'otp': otp})
    if not customer:
        return jsonify({'error': 'Customer not found'}), 404
    
    cashier = db.cashiers.find_one({'_id': ObjectId(customer['cashier_id'])})
    
    # Calculate estimated wait time
    estimated_wait_seconds = customer['position'] * calculate_wait_time(customer['cashier_id'])
    
    # Calculate time since serving started (if applicable)
    serving_time_passed = None
    if customer.get('serving_start_time'):
        serving_time_passed = (datetime.utcnow() - customer['serving_start_time']).total_seconds()
    
    return jsonify({
        'position': customer['position'],
        'status': customer['status'],
        'cashier_number': cashier['cashier_number'],
        'estimated_wait_seconds': estimated_wait_seconds,
        'serving_time_passed': serving_time_passed,
        'delays': customer.get('delays', 0)
    })

@app.route('/join/<company_code>')
def join_queue_page(company_code):
    company = db.companies.find_one({'company_code': company_code})
    if not company:
        return render_template('error.html', message='Company not found'), 404
    
    cashiers = list(db.cashiers.find({'company_id': str(company['_id']), 'is_active': True}))
    
    return render_template('join_queue.html', company=company, cashiers=cashiers)

@app.route('/api/join_queue/<company_code>', methods=['POST'])
def join_queue(company_code):
    company = db.companies.find_one({'company_code': company_code})
    if not company:
        return jsonify({'error': 'Company not found'}), 404
    
    # Find the cashier with the shortest queue
    cashiers = list(db.cashiers.find({'company_id': str(company['_id']), 'is_active': True}))
    
    if not cashiers:
        return jsonify({'error': 'No active cashiers available'}), 400
    
    shortest_queue_cashier = None
    min_queue_length = float('inf')
    
    for cashier in cashiers:
        queue_length = db.customers.count_documents({
            'cashier_id': str(cashier['_id']), 
            'status': 'waiting'
        })
        
        if queue_length < min_queue_length:
            min_queue_length = queue_length
            shortest_queue_cashier = cashier
    
    # Generate OTP
    while True:
        otp = generate_otp()
        if not db.customers.find_one({'otp': otp}):
            break
    
    # Calculate position
    position = min_queue_length + 1
    
    # Create customer in queue
    customer = {
        'cashier_id': str(shortest_queue_cashier['_id']),
        'otp': otp,
        'position': position,
        'join_time': datetime.utcnow(),
        'status': 'waiting',
        'delays': 0
    }
    
    # If this is the first customer for this cashier, mark as serving
    if position == 1:
        customer['status'] = 'serving'
        customer['serving_start_time'] = datetime.utcnow()
    
    customer_id = db.customers.insert_one(customer).inserted_id
    
    # Calculate estimated wait time
    estimated_wait_seconds = position * calculate_wait_time(str(shortest_queue_cashier['_id']))
    
    # Emit socket event if this is the first customer
    if position == 1:
        socketio.emit('customer_turn', {
            'otp': otp,
            'cashier_number': shortest_queue_cashier['cashier_number'],
            'company_code': company['company_code']
        })
    
    return jsonify({
        'success': True,
        'otp': otp,
        'position': position,
        'cashier_number': shortest_queue_cashier['cashier_number'],
        'estimated_wait_seconds': estimated_wait_seconds
    })

if __name__ == '__main__':
    # Get port from environment variable for Render compatibility
    port = int(os.getenv('PORT', 5000))
    print(f"Starting server on port {port}")
    socketio.run(app, host='0.0.0.0', port=port, debug=False, allow_unsafe_werkzeug=True) 