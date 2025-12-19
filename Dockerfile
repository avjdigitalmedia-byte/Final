# Use the official Apify Python 3.10 image
FROM apify/actor-python:3.10

# Copy the requirements file
COPY requirements.txt ./

# Install the dependencies
RUN pip install -r requirements.txt

# Copy the source code
COPY . ./

# Run the actor
CMD ["python3", "main.py"]
