"""
Enhanced logging configuration with color support for terminal output
"""

import logging
import sys


class Colors:
    """ANSI color codes for terminal output"""
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    PURPLE = '\033[95m'
    GREY = '\033[90m'
    RESET = '\033[0m'
    BLUE = '\033[96m'

class LogHelper:
    """Helper methods for formatting trading logs"""
    
    @staticmethod
    def colorize(text: str, color: str) -> str:
        """
        Apply ANSI color codes to text for terminal output
        
        Args:
            text: The text to colorize
            color: Color name ('GREEN', 'RED', 'YELLOW')
        
        Returns:
            Colored text string with ANSI codes
        """
        color_code = getattr(Colors, color.upper(), Colors.RESET)
        return f"{color_code}{text}{Colors.RESET}"
    
    @staticmethod
    def format_pnl(pnl_dollars: float, pnl_percent: float) -> str:
        """
        Format P&L with appropriate sign
        
        Args:
            pnl_dollars: P&L in dollars
            pnl_percent: P&L as percentage
        
        Returns:
            Formatted string like "+$35.12 (+0.68%)" or "-$15.25 (-0.29%)"
        """
        sign = '+' if pnl_dollars >= 0 else ''
        return f"{sign}${pnl_dollars:.2f} ({sign}{pnl_percent:.2f}%)"
    
    @staticmethod
    def determine_pnl_color(pnl_dollars: float, pnl_percent: float) -> tuple:
        """
        Determine emoji and color based on P&L thresholds
        
        Args:
            pnl_dollars: P&L in dollars
            pnl_percent: P&L as percentage
        
        Returns:
            Tuple of (emoji, color_name)
        
        Thresholds:
            - Profit: P&L > $1.00 or > 0.1%
            - Loss: P&L < -$1.00 or < -0.1%
            - Break-even: Everything else
        """
        if pnl_dollars > 1.0 or pnl_percent > 0.1:
            return "✅", "GREEN"
        elif pnl_dollars < -1.0 or pnl_percent < -0.1:
            return "❌", "RED"
        else:
            return "➖", "YELLOW"


# Create logger instance
logger = logging.getLogger('alchemy')
logger.setLevel(logging.INFO)

# Console handler
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.DEBUG)

# Formatter
formatter = logging.Formatter(
    '%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
console_handler.setFormatter(formatter)

# Add handler
logger.addHandler(console_handler)

# Prevent propagation to root logger
logger.propagate = False