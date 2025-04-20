# Virtual Queue System

A real-time queue management system that helps businesses organize customer flow.

## 🚀 Features

- **Admin Dashboard**: Complete control over queues, cashiers, and customer flow
- **Real-time Updates**: WebSocket integration for instant queue status changes
- **QR Code Integration**: Easy queue joining through scannable QR codes
- **Multi-branch Support**: Manage multiple service locations from one account
- **Analytics & Reports**: Track wait times, service efficiency, and customer flow
- **Mobile Responsive**: Works seamlessly on all devices
- **Notification System**: Alerts customers when their turn approaches

## 🛠️ Technology Stack

- **Backend**: Python, Flask, SQLite, Flask-SocketIO
- **Frontend**: HTML5, CSS3, JavaScript, Bootstrap 5
- **Real-time Communication**: Socket.IO
- **Deployment**: Railway

## 📋 Installation

### Local Development

```bash
# Clone the repository
git clone https://github.com/yourusername/virtual_queue.git
cd virtual_queue

# Create and activate virtual environment (optional but recommended)
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Run the application
python app.py
```

The application will be available at `http://localhost:5000`.

## 🚢 Deployment to Railway

### Prerequisites
- Railway account
- Git

### Deployment Steps

1. Fork or clone this repository to your GitHub account
2. Sign up for a [Railway account](https://railway.app) if you don't have one
3. Create a new project in Railway:
   - Click "New Project" 
   - Select "Deploy from GitHub repo"
   - Connect your GitHub account and select your repository
   - Railway will automatically detect the configuration

4. Add the following environment variables:
   - `SECRET_KEY`: A secure random string

## 📱 Usage Guide

### For Administrators

1. **Registration**: Create an admin account
2. **Company Setup**: Add your business details and create a unique company code
3. **Cashier Configuration**: Set up cashier points based on your service needs
4. **Queue Management**: View and manage customer queues in real-time
5. **Analytics**: Access wait time statistics and service efficiency metrics

### For Customers

1. **Join Queue**: Scan the QR code or enter the company code
2. **Receive OTP**: Get a unique OTP and position number
3. **Track Status**: Monitor queue position and estimated wait time
4. **Get Notified**: Receive alerts when your turn is approaching
5. **Service**: Proceed to the assigned cashier when called

## 📄 License

This project is licensed under the MIT License - see the LICENSE file for details.

## 📞 Contact

For support or inquiries, reach out via GitHub issues or contact the maintainer directly. 