FROM python:3.9-slim

# set working directory
WORKDIR /discord-app

# Copy requirements and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY . .

# Create Data directory
RUN mkdir -p Data

# Expose port for Flask
EXPOSE 5000

# Run the application
CMD ["python", "discord cloud no enc.py"]