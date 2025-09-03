# main_bot.py
import sys
import os

# Add current directory to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from bot.bot_runner_simple import run_bot

if __name__ == "__main__":
    run_bot()