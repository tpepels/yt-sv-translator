#!/usr/bin/env bash
set -e

# Go to the script directory (safe even if run from elsewhere)
cd "$(dirname "$0")"

# Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install --upgrade pip
if [ -f requirements.txt ]; then
    pip install -r requirements.txt
fi

echo
echo "✅ Installation complete."
echo "You can now run the program using:"
echo "   ./run.sh"
