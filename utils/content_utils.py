"""
Content utilities for handling large text content with smart truncation.
"""

def smart_truncate(content: str, max_length: int, preserve_structure: bool = True) -> str:
    """
    Smart truncation that preserves code structure when possible.
    
    Args:
        content: The content to truncate
        max_length: Maximum length to keep
        preserve_structure: If True, try to preserve code structure
        
    Returns:
        Truncated content with ellipsis if needed
    """
    if len(content) <= max_length:
        return content
        
    if not preserve_structure:
        return content[:max_length] + "..."
    
    # Try to truncate at natural boundaries
    truncated = content[:max_length]
    
    # Look for natural break points (in order of preference)
    break_points = ['\n\n', '\n', '}', ';', ')', ',', ' ']
    
    for break_point in break_points:
        last_break = truncated.rfind(break_point)
        if last_break > max_length * 0.8:  # Don't truncate too aggressively
            return truncated[:last_break + len(break_point)] + "..."
    
    # If no good break point found, just truncate
    return truncated + "..."


def estimate_token_count(text: str) -> int:
    """
    Rough estimation of token count for context window management.
    Uses simple heuristic: ~4 characters per token for code.
    """
    return len(text) // 4


def ensure_context_fits(content: str, max_tokens: int = 30000) -> str:
    """
    Ensure content fits within context window limits.
    
    Args:
        content: Content to check
        max_tokens: Maximum tokens allowed (default: 30k out of 128k)
        
    Returns:
        Content that fits within token limits
    """
    estimated_tokens = estimate_token_count(content)
    
    if estimated_tokens <= max_tokens:
        return content
    
    # Calculate safe character limit
    safe_char_limit = max_tokens * 4  # 4 chars per token estimate
    
    return smart_truncate(content, safe_char_limit, preserve_structure=True)