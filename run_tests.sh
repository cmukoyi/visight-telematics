#!/bin/bash
# Local test runner before deployment
# Usage: ./run_tests.sh

set -e

echo "================================"
echo "🧪 Running Backend Tests"
echo "================================"
echo ""

cd "$(dirname "$0")/backend" || exit 1

# Check if venv exists
if [ ! -d "venv" ]; then
    echo "⚠️  Virtual environment not found. Creating..."
    python3 -m venv venv
fi

# Activate venv
source venv/bin/activate || . venv/Scripts/activate

# Install dev dependencies
echo "📦 Installing test dependencies..."
pip install -q -r requirements.txt
pip install -q -r requirements-dev.txt

# Run pytest with coverage
echo ""
echo "🚀 Running pytest..."
pytest \
    tests/ \
    --cov=app \
    --cov-report=term-missing \
    --cov-report=html \
    -v

# Check coverage
COVERAGE_MIN=60
echo ""
echo "📊 Coverage report generated in htmlcov/index.html"

echo ""
echo "✅ All tests passed!"
echo ""
echo "Next steps:"
echo "  1. Review test output above"
echo "  2. If all tests passed, push to git:"
echo "     git add ."
echo "     git commit -m 'feat: add feature'"
echo "     git push origin main"
echo ""
