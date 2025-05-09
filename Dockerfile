# Use an official Python runtime as a parent image
FROM python:3.10-slim

# Set the working directory in the container
WORKDIR /app

# Copy the requirements file into the container at /app
COPY requirements.txt .

# Install any needed packages specified in requirements.txt
# --no-cache-dir reduces image size
# --trusted-host to avoid warnings/errors behind proxies if needed (optional)
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code into the container at /app
COPY . .

# Make port 5000 available to the world outside this container
EXPOSE 5000

# Define environment variable for Flask (optional, can be set in docker-compose too)
ENV FLASK_APP=app.py
# Set to production mode
ENV FLASK_ENV=production 
# Recommended: Set SECRET_KEY via environment variable in docker-compose.yml
# ENV FLASK_SECRET_KEY='your-production-secret-key'

# Command to run the application using Gunicorn WSGI server
# Bind to 0.0.0.0 to accept connections from any IP
# Use a few workers for better concurrency (adjust based on resources)
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "4", "app:app"]