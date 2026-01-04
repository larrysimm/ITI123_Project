# 1. Base Image: Use a lightweight Python version
FROM python:3.10-slim

# 2. Environment Variables to prevent Python from writing pyc files to disc
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# 3. Work Directory: Create a folder inside the container
WORKDIR /app

# 4. Install Dependencies
# We copy requirements FIRST to leverage Docker caching. 
# If requirements.txt doesn't change, Docker skips this step on re-builds (FASTER!)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 5. Copy Application Code
# This includes main.py, database.py, skills.db, and star_guide.pdf
COPY . .

# 6. Run the Application
# Render provides the PORT variable automatically.
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]