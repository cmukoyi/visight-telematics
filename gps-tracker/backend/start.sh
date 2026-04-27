#!/bin/bash

# Load environment variables from .env file
export $(grep -v '^#' .env | xargs)

# Start the backend
python3 -m uvicorn app.main:app --host 0.0.0.0 --port 5001 --reload
