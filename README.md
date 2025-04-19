# Virtual Queue System

A web-based queue management system for businesses with real-time updates and mobile accessibility through QR codes.

## Features

- Admin interface for managing queues
- Customer interface for joining queues via QR code
- Real-time updates using WebSockets
- OTP-based queue tracking
- Analytics and queue statistics
- Mobile-friendly design

## Deployment to Railway

### 1. Fork or Clone this Repository

Clone this repository to your account.

### 2. Create Railway Account

- Sign up at [Railway.app](https://railway.app/)
- Install the Railway CLI (optional)

### 3. Deploy to Railway

#### Option 1: Deploy via Railway Dashboard

1. Create a new project in Railway
2. Choose "Deploy from GitHub repo"
3. Select this repository
4. Railway will automatically detect the configuration and deploy

#### Option 2: Deploy via CLI

```bash
# Login to Railway
railway login

# Initialize project
railway init

# Deploy project
railway up
```

### 4. Add PostgreSQL Database

1. In your Railway project, go to "New Service" → "Database" → "PostgreSQL"
2. Railway will automatically connect the database to your application

### 5. Set Environment Variables

Add the following environment variables in the Railway dashboard:
- `SECRET_KEY`: A secure random string for Flask sessions
- `PORT`: 5000 (or any port)

### 6. Access Your Application

After deployment, Railway will provide a URL to access your application.

## Local Development

```bash
# Install dependencies
pip install -r requirements.txt

# Run the application
python app.py
```

## Usage

### Admin

1. Register a new admin account
2. Create a company profile
3. Set up cashiers/service points
4. Share the generated QR code with customers

### Customers

1. Scan the QR code or enter the company code
2. Receive an OTP and position number
3. Monitor queue status in real-time
4. Proceed to the assigned cashier when notified 