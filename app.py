from flask import Flask, request, jsonify, render_template
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import time
import os
import openai
from dotenv import load_dotenv
import re
import logging
import validators
from urllib.robotparser import RobotFileParser
import socket
import concurrent.futures
from functools import partial
from datetime import datetime
from email.utils import parsedate_to_datetime
import json

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Add structured logging function
def log_request(url, output_type, success, error=None, processing_time=None, word_count=None):
    """
    Log request details in structured JSON format for better analysis.
    
    Args:
        url (str): The requested URL
        output_type (str): Type of output requested
        success (bool): Whether the request was successful
        error (str, optional): Error message if failed
        processing_time (float, optional): Time taken to process
        word_count (int, optional): Number of words processed
    """
    log_entry = {
        "timestamp": datetime.now().isoformat(),
        "url": url,
        "output_type": output_type,
        "success": success,
        "error": error,
        "processing_time_seconds": processing_time,
        "word_count": word_count,
        "user_agent": request.headers.get('User-Agent', 'Unknown'),
        "ip_address": request.remote_addr
    }
    
    if success:
        logger.info(f"Request processed successfully: {json.dumps(log_entry)}")
    else:
        logger.error(f"Request failed: {json.dumps(log_entry)}")

# Load environment variables
load_dotenv()

# Get API key from environment variable
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
# Set a default if no environment variable is set (for development only)
if not OPENAI_API_KEY:
    logger.warning("No OpenAI API key found. Using default client for demo purposes.")
    # This will help developers understand they need to set up their API key

# Set up OpenAI client
openai_client = openai.OpenAI(api_key=OPENAI_API_KEY)

# MAX_LINKS_TO_PROCESS has been removed to process all valid links

# Request timeout in seconds
REQUEST_TIMEOUT = int(os.environ.get("REQUEST_TIMEOUT", 15))
# Number of concurrent workers for processing
CONCURRENT_WORKERS = int(os.environ.get("CONCURRENT_WORKERS", 10))
# Delay between API calls in seconds (to avoid rate limiting)
API_CALL_DELAY = float(os.environ.get("API_CALL_DELAY", 0.5))

app = Flask(__name__)

# Enhanced Error Handlers
@app.errorhandler(400)
def bad_request(error):
    """Handle 400 Bad Request errors."""
    return jsonify({
        "error": "Bad Request",
        "message": "The request could not be processed due to invalid input.",
        "status_code": 400
    }), 400

@app.errorhandler(404)
def not_found(error):
    """Handle 404 Not Found errors."""
    return jsonify({
        "error": "Not Found",
        "message": "The requested resource was not found.",
        "status_code": 404
    }), 404

@app.errorhandler(405)
def method_not_allowed(error):
    """Handle 405 Method Not Allowed errors."""
    return jsonify({
        "error": "Method Not Allowed",
        "message": "The HTTP method is not allowed for this endpoint.",
        "status_code": 405
    }), 405

@app.errorhandler(429)
def too_many_requests(error):
    """Handle 429 Too Many Requests errors."""
    return jsonify({
        "error": "Too Many Requests",
        "message": "Rate limit exceeded. Please try again later.",
        "status_code": 429
    }), 429

@app.errorhandler(500)
def internal_error(error):
    """Handle 500 Internal Server Error."""
    logger.error(f"Internal server error: {str(error)}")
    return jsonify({
        "error": "Internal Server Error",
        "message": "An unexpected error occurred. Please try again later.",
        "status_code": 500
    }), 500

@app.errorhandler(503)
def service_unavailable(error):
    """Handle 503 Service Unavailable errors."""
    return jsonify({
        "error": "Service Unavailable",
        "message": "The service is temporarily unavailable. Please try again later.",
        "status_code": 503
    }), 503

@app.errorhandler(Exception)
def handle_exception(error):
    """Handle any unhandled exceptions."""
    logger.error(f"Unhandled exception: {str(error)}", exc_info=True)
    return jsonify({
        "error": "Internal Server Error",
        "message": "An unexpected error occurred. Please try again later.",
        "status_code": 500
    }), 500

def validate_url(url):
    """
    Validate if the provided URL is valid and safe to access.
    Enhanced with additional security checks and validation.
    
    Args:
        url (str): The URL to validate
        
    Returns:
        tuple: (is_valid, error_message)
    """
    # Basic URL format validation
    if not url or not isinstance(url, str):
        return False, "URL is required and must be a string"
    
    # Check URL length limit
    if len(url) > 2048:
        return False, "URL too long (maximum 2048 characters)"
    
    # Check if URL starts with http:// or https://
    if not url.startswith(('http://', 'https://')):
        return False, "URL must start with http:// or https://"
    
    # Check for suspicious patterns
    suspicious_patterns = ['javascript:', 'data:', 'file:', 'ftp:', 'mailto:', 'tel:']
    if any(pattern in url.lower() for pattern in suspicious_patterns):
        return False, "Invalid URL scheme detected"
    
    # Check for potential injection patterns
    injection_patterns = ['<script', 'javascript:', 'vbscript:', 'onload=', 'onerror=']
    if any(pattern in url.lower() for pattern in injection_patterns):
        return False, "URL contains potentially malicious content"
    
    # Use validators library for comprehensive URL validation
    if not validators.url(url):
        return False, "Invalid URL format"
    
    # Parse URL to check components
    try:
        parsed_url = urlparse(url)
        # Verify netloc (domain) exists
        if not parsed_url.netloc:
            return False, "URL missing domain name"
        
        # Check for localhost or private IP addresses (optional security measure)
        if parsed_url.netloc in ['localhost', '127.0.0.1', '0.0.0.0']:
            return False, "Local URLs are not allowed for security reasons"
        
        # Check if domain resolves (optional, but helpful to catch typos)
        try:
            socket.gethostbyname(parsed_url.netloc)
        except socket.gaierror:
            return False, f"Could not resolve domain: {parsed_url.netloc}"
        
    except Exception as e:
        return False, f"URL parsing error: {str(e)}"
    
    return True, ""

def check_robots_txt(url):
    """
    Check robots.txt to see if scraping is allowed for the provided URL.
    This is a simple implementation for demonstration purposes.
    
    Args:
        url (str): The URL to check
        
    Returns:
        bool: True if scraping is allowed, False otherwise
    """
    try:
        parsed_url = urlparse(url)
        robots_url = f"{parsed_url.scheme}://{parsed_url.netloc}/robots.txt"
        
        rp = RobotFileParser()
        rp.set_url(robots_url)
        rp.read()
        
        # Check if scraping is allowed for our user agent
        user_agent = "DeadassLead_Basic"  # You could customize this
        can_fetch = rp.can_fetch(user_agent, url)
        
        if not can_fetch:
            logger.warning(f"Scraping not allowed by robots.txt for {url}")
        
        return can_fetch
    except Exception as e:
        logger.warning(f"Error checking robots.txt: {str(e)}")
        # If we can't check robots.txt, we'll proceed with caution
        return True

def clean_text(text):
    """
    Clean the text by removing extra whitespace and non-essential characters.
    
    Args:
        text (str): The text to clean
        
    Returns:
        str: Cleaned text
    """
    # Replace multiple spaces with a single space
    text = re.sub(r'\s+', ' ', text)
    # Remove non-printable characters
    text = re.sub(r'[^\x20-\x7E]', '', text)
    return text.strip()

def ensure_utf8_and_unix_line_endings(text):
    """
    Ensure text is properly encoded in UTF-8 and uses Unix line endings.
    
    Args:
        text (str): The text to process
        
    Returns:
        str: Processed text with proper encoding and line endings
    """
    if not text:
        return text
    
    # Convert to string if needed
    if not isinstance(text, str):
        text = str(text)
    
    # Normalize line endings to Unix style
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    
    # Handle common encoding issues
    text = text.encode('utf-8', errors='ignore').decode('utf-8')
    
    return text

def validate_and_fix_encoding(text):
    """
    Validate and fix encoding issues in text.
    
    Args:
        text (str): The text to validate and fix
        
    Returns:
        str: Fixed text
    """
    if not text:
        return text
    
    # Remove problematic characters
    text = re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]', '', text)
    
    # Fix common encoding issues
    text = text.replace('\ufffd', '')  # Remove replacement characters
    
    return text

def convert_html_to_markdown(html_content):
    """
    Convert HTML content to Markdown format while preserving structure.
    
    Args:
        html_content (str): HTML content to convert
        
    Returns:
        str: Markdown formatted content
    """
    if not html_content:
        return html_content
    
    # Convert common HTML elements to Markdown
    markdown = html_content
    
    # Headers
    markdown = re.sub(r'<h1[^>]*>(.*?)</h1>', r'# \1', markdown, flags=re.IGNORECASE | re.DOTALL)
    markdown = re.sub(r'<h2[^>]*>(.*?)</h2>', r'## \1', markdown, flags=re.IGNORECASE | re.DOTALL)
    markdown = re.sub(r'<h3[^>]*>(.*?)</h3>', r'### \1', markdown, flags=re.IGNORECASE | re.DOTALL)
    markdown = re.sub(r'<h4[^>]*>(.*?)</h4>', r'#### \1', markdown, flags=re.IGNORECASE | re.DOTALL)
    markdown = re.sub(r'<h5[^>]*>(.*?)</h5>', r'##### \1', markdown, flags=re.IGNORECASE | re.DOTALL)
    markdown = re.sub(r'<h6[^>]*>(.*?)</h6>', r'###### \1', markdown, flags=re.IGNORECASE | re.DOTALL)
    
    # Bold and italic
    markdown = re.sub(r'<strong[^>]*>(.*?)</strong>', r'**\1**', markdown, flags=re.IGNORECASE | re.DOTALL)
    markdown = re.sub(r'<b[^>]*>(.*?)</b>', r'**\1**', markdown, flags=re.IGNORECASE | re.DOTALL)
    markdown = re.sub(r'<em[^>]*>(.*?)</em>', r'*\1*', markdown, flags=re.IGNORECASE | re.DOTALL)
    markdown = re.sub(r'<i[^>]*>(.*?)</i>', r'*\1*', markdown, flags=re.IGNORECASE | re.DOTALL)
    
    # Links
    markdown = re.sub(r'<a[^>]*href=["\']([^"\']*)["\'][^>]*>(.*?)</a>', r'[\2](\1)', markdown, flags=re.IGNORECASE | re.DOTALL)
    
    # Lists
    markdown = re.sub(r'<ul[^>]*>(.*?)</ul>', r'\1', markdown, flags=re.IGNORECASE | re.DOTALL)
    markdown = re.sub(r'<ol[^>]*>(.*?)</ol>', r'\1', markdown, flags=re.IGNORECASE | re.DOTALL)
    markdown = re.sub(r'<li[^>]*>(.*?)</li>', r'- \1', markdown, flags=re.IGNORECASE | re.DOTALL)
    
    # Paragraphs
    markdown = re.sub(r'<p[^>]*>(.*?)</p>', r'\1\n\n', markdown, flags=re.IGNORECASE | re.DOTALL)
    
    # Blockquotes
    markdown = re.sub(r'<blockquote[^>]*>(.*?)</blockquote>', r'> \1', markdown, flags=re.IGNORECASE | re.DOTALL)
    
    # Code blocks
    markdown = re.sub(r'<pre[^>]*>(.*?)</pre>', r'```\n\1\n```', markdown, flags=re.IGNORECASE | re.DOTALL)
    markdown = re.sub(r'<code[^>]*>(.*?)</code>', r'`\1`', markdown, flags=re.IGNORECASE | re.DOTALL)
    
    # Remove remaining HTML tags
    markdown = re.sub(r'<[^>]+>', '', markdown)
    
    # Clean up extra whitespace
    markdown = re.sub(r'\n\s*\n\s*\n', '\n\n', markdown)
    markdown = markdown.strip()
    
    return markdown

def convert_inline_markdown(text):
    """
    Convert inline HTML formatting to Markdown.
    
    Args:
        text (str): Text with inline HTML
        
    Returns:
        str: Text with Markdown formatting
    """
    if not text:
        return text
    
    # Bold
    text = re.sub(r'<strong[^>]*>(.*?)</strong>', r'**\1**', text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r'<b[^>]*>(.*?)</b>', r'**\1**', text, flags=re.IGNORECASE | re.DOTALL)
    
    # Italic
    text = re.sub(r'<em[^>]*>(.*?)</em>', r'*\1*', text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r'<i[^>]*>(.*?)</i>', r'*\1*', text, flags=re.IGNORECASE | re.DOTALL)
    
    # Links
    text = re.sub(r'<a[^>]*href=["\']([^"\']*)["\'][^>]*>(.*?)</a>', r'[\2](\1)', text, flags=re.IGNORECASE | re.DOTALL)
    
    # Code
    text = re.sub(r'<code[^>]*>(.*?)</code>', r'`\1`', text, flags=re.IGNORECASE | re.DOTALL)
    
    return text

def extract_main_content_with_markdown(soup):
    """
    Extract main content from the page with markdown preservation.
    
    Args:
        soup (BeautifulSoup): The parsed HTML
        
    Returns:
        str: Main content in markdown format
    """
    # Remove likely irrelevant elements
    for element in soup.find_all(['nav', 'footer', 'aside', 'style', 'script', 'noscript', 'header']):
        element.decompose()
    
    # Priority 1: Check for main content tags
    main_content_selectors = [
        'main', 'article', 'div[role="main"]', '.main-content', '.content', '.article',
        '.post-content', '.entry-content', '.article-content', '.blog-content',
        '.tool-description', '.product-description', '.page-content',
        '.page-body', '.post-body', '.entry-body', '.content-body',
        '.main-text', '.post-text', '.article-text', '.content-text'
    ]
    
    main_content = ""
    for selector in main_content_selectors:
        elements = soup.select(selector)
        for element in elements:
            # Convert HTML to markdown
            element_html = str(element)
            element_markdown = convert_html_to_markdown(element_html)
            if element_markdown and len(element_markdown) > 50:
                main_content += element_markdown + "\n\n"
    
    # Priority 2: If no main content found, look for content blocks
    if not main_content:
        for section_tag in ['section', 'div[class*="content"]', 'div[class*="article"]', 'div[class*="post"]', 'div[class*="text"]', 'div[class*="body"]']:
            elements = []
            if section_tag.startswith('div[class*='):
                class_pattern = section_tag.split('"')[1]
                elements = soup.find_all('div', class_=lambda c: c and class_pattern in c)
            else:
                elements = soup.find_all(section_tag)
                
            for element in elements:
                element_html = str(element)
                element_markdown = convert_html_to_markdown(element_html)
                if element_markdown and len(element_markdown) > 100:
                    main_content += element_markdown + "\n\n"
    
    # Priority 3: Fallback to paragraphs
    if not main_content:
        paragraphs = soup.find_all('p')
        for p in paragraphs:
            p_html = str(p)
            p_markdown = convert_html_to_markdown(p_html)
            if p_markdown and len(p_markdown) > 50:
                main_content += p_markdown + "\n\n"
    
    # Priority 4: Last resort - get all text from body
    if not main_content and soup.body:
        body_html = str(soup.body)
        main_content = convert_html_to_markdown(body_html)
    
    # Clean and validate encoding
    main_content = ensure_utf8_and_unix_line_endings(main_content)
    main_content = validate_and_fix_encoding(main_content)
    main_content = clean_text(main_content)
    
    # Limit content length
    if len(main_content) > 4000:
        cut_point = 3950
        while cut_point < 4000 and cut_point < len(main_content):
            if main_content[cut_point] in ['.', '!', '?'] and (cut_point + 1 >= len(main_content) or main_content[cut_point + 1] == ' '):
                cut_point += 1
                break
            cut_point += 1
        
        if cut_point >= 4000:
            cut_point = 3990
            while cut_point > 3900 and cut_point < len(main_content):
                if main_content[cut_point] == ' ':
                    break
                cut_point -= 1
                
        main_content = main_content[:cut_point].strip()
    
    return main_content

def extract_main_content(soup):
    """
    Extract the main content from the page with improved focus on relevance.
    Aggressive enough to get meaningful content but avoids irrelevant elements.
    
    Args:
        soup (BeautifulSoup): The parsed HTML
        
    Returns:
        str: The main content text
    """
    # Try to find main content areas
    main_content = ""
    
    # First, remove likely irrelevant elements
    for element in soup.find_all(['nav', 'footer', 'aside', 'style', 'script', 'noscript']):
        element.decompose()
    
    # Priority 1: Check for main content tags with improved selection
    main_content_selectors = [
        'main', 'article', 'div[role="main"]', '.main-content', '.content', '.article',
        '.post-content', '.entry-content', '.article-content', '.blog-content',
        '.tool-description', '.product-description', '.page-content',
        '.page-body', '.post-body', '.entry-body', '.content-body',
        '.main-text', '.post-text', '.article-text', '.content-text'
    ]
    
    for tag in main_content_selectors:
        elements = []
        if tag.startswith('.'):
            elements = soup.select(tag)
        elif '[' in tag and ']' in tag:
            tag_name, attr = tag.split('[', 1)
            attr_name, attr_value = attr.rstrip(']').split('=')
            attr_value = attr_value.strip('"\'')
            elements = soup.find_all(tag_name, attrs={attr_name: attr_value})
        else:
            elements = soup.find_all(tag)
            
        if elements:
            for element in elements:
                # Extract text with better whitespace handling
                element_text = ' '.join(element.get_text(strip=True, separator=' ').split())
                if element_text:
                    main_content += element_text + " "
            if main_content:
                break
    
    # Priority 2: If no main content found, look for content blocks/sections
    if not main_content:
        for section_tag in ['section', 'div[class*="content"]', 'div[class*="article"]', 'div[class*="post"]', 'div[class*="text"]', 'div[class*="body"]']:
            elements = []
            if section_tag.startswith('div[class*='):
                class_pattern = section_tag.split('"')[1]
                elements = soup.find_all('div', class_=lambda c: c and class_pattern in c)
            elif section_tag.startswith('.'):
                elements = soup.select(section_tag)
            else:
                elements = soup.find_all(section_tag)
                
            if elements:
                for element in elements:
                    # Filter out small sections that are likely navigation/sidebars
                    element_text = ' '.join(element.get_text(strip=True, separator=' ').split())
                    if len(element_text) > 100:  # Only consider substantial sections
                        main_content += element_text + " "
                if main_content:
                    break
    
    # Priority 3: If still no content, extract meaningful paragraphs
    if not main_content:
        paragraphs = soup.find_all('p')
        for p in paragraphs:
            p_text = p.get_text(strip=True)
            if len(p_text) > 50:  # Only consider substantial paragraphs
                main_content += p_text + " "
    
    # Priority 4: If still no content, get all text from body excluding common irrelevant elements
    if not main_content and soup.body:
        # Remove likely navigation, header, footer elements
        for nav in soup.body.find_all(['nav', 'header', 'footer']):
            nav.decompose()
            
        main_content = ' '.join(soup.body.get_text(strip=True, separator=' ').split())
    
    # Clean and limit content
    main_content = clean_text(main_content)
    
    # Limit to 4000 characters while preserving coherence
    if len(main_content) > 4000:
        # Find a good ending point around the 4000 character mark
        cut_point = 3950
        # Look for a sentence end within the last 200 characters of our limit
        while cut_point < 4000 and cut_point < len(main_content):
            if main_content[cut_point] in ['.', '!', '?'] and (cut_point + 1 >= len(main_content) or main_content[cut_point + 1] == ' '):
                cut_point += 1
                break
            cut_point += 1
            
        # If we didn't find a good sentence end, look for a space to avoid cutting words
        if cut_point >= 4000 or cut_point >= len(main_content):
            cut_point = 3990
            while cut_point > 3900 and cut_point < len(main_content):
                if main_content[cut_point] == ' ':
                    break
                cut_point -= 1
                
        main_content = main_content[:cut_point].strip()
        
    return main_content

def clean_summary(summary, max_words=160):
    """
    Clean and truncate a summary to ensure it's concise and ends at a natural point.
    Updated to handle word-based truncation for 160-word summaries.
    
    Args:
        summary (str): The summary to clean
        max_words (int): Maximum number of words for the summary
        
    Returns:
        str: Cleaned and properly truncated summary
    """
    if not summary:
        return summary
        
    # First, clean up any extra whitespace
    summary = ' '.join(summary.split())
    
    # Remove any artificially added ellipses at the end that aren't part of a sentence
    if summary.endswith('...') and not summary[:-3].endswith('.'):
        summary = summary[:-3].strip()
    
    # Split into words
    words = summary.split()
    
    # If it's within word limits, return as is
    if len(words) <= max_words:
        return summary
    
    # Find the best point to cut the summary
    # Start looking from 10 words before the max_words to ensure we find a good break
    safety_margin = 10
    cut_search_start = max(0, max_words - safety_margin)
    
    # First priority: Find a sentence end (period, exclamation, question mark)
    best_end = -1
    for i in range(cut_search_start, min(max_words, len(words))):
        word = words[i]
        if word.endswith(('.', '!', '?')):
            best_end = i + 1
            break
    
    # If we found a good sentence end, use it
    if best_end > 0:
        return ' '.join(words[:best_end]).strip()
    
    # Second priority: Find a phrase break (comma, semicolon, colon)
    for i in range(cut_search_start, min(max_words, len(words))):
        word = words[i]
        if word.endswith((',', ';', ':')):
            best_end = i + 1
            break
    
    # If we found a phrase break, use it
    if best_end > 0:
        return ' '.join(words[:best_end]).strip()
    
    # Third priority: Find a conjunction or preposition
    conjunctions = ['and', 'but', 'or', 'nor', 'for', 'so', 'yet', 'with', 'to']
    for i in range(cut_search_start, min(max_words, len(words))):
        if words[i].lower() in conjunctions:
            best_end = i + 1
            break
    
    # If we found a conjunction, cut there
    if best_end > 0:
        return ' '.join(words[:best_end]).strip()
    
    # Last resort: Cut at max_words
    return ' '.join(words[:max_words]).strip()

def get_page_summary(page_url, link_title=None):
    """
    Get a concise summary of a web page using LLM.
    
    Args:
        page_url (str): The URL of the page to summarize
        link_title (str, optional): The title of the link for additional context
        
    Returns:
        str: A concise summary of the page
    """
    try:
        # Check if we should respect robots.txt
        if not check_robots_txt(page_url):
            return f"Respecting robots.txt: Not allowed to access {page_url}"
        
        # Fetch the page
        logger.info(f"Fetching page: {page_url}")
        try:
            response = requests.get(page_url, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
        except requests.exceptions.Timeout:
            logger.error(f"Timeout error fetching {page_url}")
            return f"Timeout accessing: {page_url}"
        except requests.exceptions.ConnectionError:
            logger.error(f"Connection error fetching {page_url}")
            return f"Connection error: {page_url}"
        except requests.exceptions.HTTPError as e:
            status_code = e.response.status_code if e.response else "unknown"
            logger.error(f"HTTP error {status_code} fetching {page_url}")
            return f"HTTP error {status_code}: {page_url}"
        except requests.exceptions.RequestException as e:
            logger.error(f"Request error for {page_url}: {str(e)}")
            return f"Error accessing: {page_url}"
        
        # Parse HTML
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Extract main content
        page_content = extract_main_content(soup)
        
        if not page_content:
            # No content found, try fallbacks
            logger.warning(f"No main content found for {page_url}, using fallback")
            return get_fallback_summary(soup, page_url, link_title)
        
        # Attempt to summarize using LLM
        if OPENAI_API_KEY:
            try:
                logger.info(f"Calling LLM for page: {page_url}")
                
                # Add a small delay to avoid rate limiting
                time.sleep(API_CALL_DELAY)
                
                # Create a focused prompt for 160-word summaries
                context = f"The page is titled '{link_title}'. " if link_title else ""
                prompt = (
                    f"{context}Provide a comprehensive 160-word summary of the following web page content. "
                    f"Include the main topics, key points, and important details. "
                    f"Make it informative, well-structured, and engaging. "
                    f"Focus on what makes this page valuable to readers:\n\n{page_content}"
                )
                
                # Call OpenAI API with settings for 160-word summaries
                response = openai_client.chat.completions.create(
                    model="gpt-3.5-turbo",
                    messages=[
                        {"role": "system", "content": "You are a helpful assistant that creates comprehensive 160-word summaries of web page content. Focus on key information, main topics, and valuable insights."},
                        {"role": "user", "content": prompt}
                    ],
                    max_tokens=300,  # Increased for 160-word summaries
                    temperature=0.4,  # Slightly higher for more creative summaries
                    presence_penalty=0.0  # Neutral to allow natural flow
                )
                
                # Extract summary from response
                summary = response.choices[0].message.content.strip()
                
                # Clean and properly truncate the summary to 160 words
                summary = clean_summary(summary, 160)
                
                logger.info(f"Successfully summarized page: {page_url}")
                return summary
            
            except openai.RateLimitError as e:
                logger.error(f"OpenAI rate limit exceeded for {page_url}: {str(e)}")
                return get_fallback_summary(soup, page_url, link_title, error_prefix="Rate limit exceeded: ")
            
            except openai.APIError as e:
                logger.error(f"OpenAI API error for {page_url}: {str(e)}")
                return get_fallback_summary(soup, page_url, link_title, error_prefix="API error: ")
            
            except openai.APIConnectionError as e:
                logger.error(f"OpenAI connection error for {page_url}: {str(e)}")
                return get_fallback_summary(soup, page_url, link_title, error_prefix="Connection error: ")
            
            except openai.AuthenticationError as e:
                logger.error(f"OpenAI authentication error: {str(e)}")
                return get_fallback_summary(soup, page_url, link_title, error_prefix="Auth error: ")
            
            except Exception as e:
                logger.error(f"LLM error for {page_url}: {str(e)}")
                # Fall back to alternative method
                return get_fallback_summary(soup, page_url, link_title, error_prefix="Error: ")
        else:
            # No API key, use fallback
            logger.warning(f"No API key available, using fallback for: {page_url}")
            return get_fallback_summary(soup, page_url, link_title)
            
    except Exception as e:
        logger.error(f"Unexpected error summarizing {page_url}: {str(e)}")
        # If we have a link title, use it as a fallback
        if link_title:
            return f"Page about {link_title}"
        return f"Could not summarize: {page_url}"

def get_fallback_summary(soup, page_url, link_title=None, error_prefix=""):
    """
    Get a fallback summary when LLM summarization fails.
    
    Args:
        soup (BeautifulSoup): The parsed HTML
        page_url (str): The URL of the page
        link_title (str, optional): The title of the link for additional context
        error_prefix (str, optional): Prefix to add to error messages
        
    Returns:
        str: A fallback summary
    """
    # Try meta description
    meta_desc = soup.find('meta', attrs={'name': 'description'})
    if meta_desc and meta_desc.get('content'):
        description = meta_desc.get('content').strip()
        if description:
            # Clean and properly truncate
            return clean_summary(description, 160)
    
    # Try page title
    if soup.title and soup.title.string:
        title = soup.title.string.strip()
        if title:
            return clean_summary(title, 160)
    
    # Try first paragraphs
    paragraphs = soup.find_all('p')
    content = ""
    for p in paragraphs[:3]:  # Get first 3 paragraphs
        p_text = p.get_text(strip=True)
        if p_text and len(p_text) > 20:  # Only consider substantial paragraphs
            content += p_text + " "
            if len(content) > 50:  # Once we have enough content, break
                break
    
    if content:
        content = clean_text(content)
        return clean_summary(content, 160)
    
    # Use link title if available
    if link_title:
        return f"{error_prefix}Page about {link_title}"
    
    # Last resort
    return f"{error_prefix}Page at {page_url}"

def format_llms_text(website_url, site_description, successful_links, failed_links):
    """
    Format the llms.txt content with separate sections for successful and failed pages.
    
    Args:
        website_url (str): The main website URL
        site_description (str): The site description
        successful_links (list): List of dictionaries with 'summary', 'url', and 'title' keys
        failed_links (list): List of dictionaries with 'url', 'title', and 'error' keys
        
    Returns:
        str: Formatted llms.txt content
    """
    # Get domain name from URL
    parsed_url = urlparse(website_url)
    domain_name = parsed_url.netloc
    
    # Get current timestamp
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # Calculate total pages
    total_pages = len(successful_links) + len(failed_links)
    
    # Format the header with site information
    llms_text = f"Site: {domain_name}\n"
    llms_text += f"Generated: {current_time}\n"
    llms_text += f"Total-Pages: {total_pages}\n\n"
    
    # Add site description
    llms_text += f"> {site_description}\n\n"
    
    # Add successful pages section
    if successful_links:
        llms_text += "## Successfully Processed Pages\n\n"
        
        # Sort the successful links alphabetically by link title
        sorted_successful = sorted(successful_links, key=lambda x: x["title"].lower())
        
        # Add each successful link in the format: - [Link Title](URL): Summary
        for link in sorted_successful:
            title = link["title"].strip()
            url = link["url"].strip()
            summary = link["summary"].strip()
            
            # Ensure the summary doesn't start with the title to avoid redundancy
            if summary.lower().startswith(title.lower() + " "):
                summary = summary[len(title):].strip()
                # Remove leading punctuation if present
                if summary and summary[0] in ['-', ':', ',', ';']:
                    summary = summary[1:].strip()
            
            llms_text += f"- [{title}]({url}): {summary}\n"
        
        llms_text += "\n"
    
    # Add failed pages section
    if failed_links:
        llms_text += "## Failed Pages\n\n"
        
        # Sort the failed links alphabetically by link title
        sorted_failed = sorted(failed_links, key=lambda x: x["title"].lower())
        
        # Add each failed link with error details
        for link in sorted_failed:
            title = link["title"].strip()
            url = link["url"].strip()
            error = link["error"].strip()
            
            llms_text += f"- [{title}]({url}): Failed to process - {error}\n"
        
        llms_text += "\n"
    
    # Add summary statistics
    total_pages = len(successful_links) + len(failed_links)
    success_rate = (len(successful_links) / total_pages * 100) if total_pages > 0 else 0
    
    llms_text += f"## Summary\n"
    llms_text += f"- Total pages discovered: {total_pages}\n"
    llms_text += f"- Successfully processed: {len(successful_links)}\n"
    llms_text += f"- Failed to process: {len(failed_links)}\n"
    llms_text += f"- Success rate: {success_rate:.1f}%\n"
    
    return llms_text

def extract_site_description(soup, website_url):
    """
    Extract the site description, RELENTLESSLY prioritizing meta description tag.
    
    Args:
        soup (BeautifulSoup): The parsed HTML
        website_url (str): The URL of the website
        
    Returns:
        str: The site description
    """
    # ABSOLUTE FIRST PRIORITY: Standard meta name="description" tag
    meta_desc = soup.find('meta', attrs={'name': 'description'})
    
    # If standard meta description is found with ANY content, use it immediately
    if meta_desc and meta_desc.get('content'):
        description = meta_desc.get('content').strip()
        if description:  # Any non-empty string is acceptable
            logger.info("Using standard meta description for site description")
            return description
    
    # Only proceed to alternatives if standard meta description was not found or empty
    logger.warning("Standard meta description not found or empty, trying alternative meta tags")
    
    # Try Open Graph description
    og_desc = soup.find('meta', attrs={'property': 'og:description'})
    if og_desc and og_desc.get('content'):
        description = og_desc.get('content').strip()
        if description:
            logger.info("Using Open Graph description for site description")
            return description
    
    # Try Twitter description
    twitter_desc = soup.find('meta', attrs={'property': 'twitter:description'})
    if twitter_desc and twitter_desc.get('content'):
        description = twitter_desc.get('content').strip()
        if description:
            logger.info("Using Twitter description for site description")
            return description
    
    # Log that we're falling back to non-meta tag methods
    logger.warning("No meta description tags found, using fallback methods")
    
    # FALLBACK: Only executed if no meta description tags found
    
    # Try to find headings first
    headings = []
    for h_tag in ['h1', 'h2']:
        elements = soup.find_all(h_tag)
        for element in elements:
            text = element.get_text(strip=True)
            if text and len(text) > 15:  # Only consider substantial headings
                headings.append(text)
    
    # Try prominent paragraphs
    paragraphs = []
    for p in soup.find_all('p'):
        p_text = p.get_text(strip=True)
        if p_text and len(p_text) > 50:  # Only consider substantial paragraphs
            paragraphs.append(p_text)
    
    # Use headings + first paragraph if available
    if headings and paragraphs:
        combined = f"{headings[0]} - {paragraphs[0]}"
        # Ensure it's not too long (150-200 chars)
        if len(combined) > 200:
            # Find a good ending point (end of sentence or phrase)
            cut_point = 180
            while cut_point < min(200, len(combined)) and combined[cut_point] not in ['.', '!', '?', ',', ';', ':']:
                cut_point += 1
            
            if cut_point < len(combined):
                # We found a good breaking point
                combined = combined[:cut_point + 1]
            else:
                # No good breaking point, just truncate
                combined = combined[:200]
                
        logger.info("Using heading + paragraph for site description")
        return combined
    
    # Just use headings if available
    if headings:
        description = headings[0]
        if len(description) > 200:
            description = description[:200]
        logger.info("Using heading for site description")
        return description
    
    # Just use first paragraph if available
    if paragraphs:
        description = paragraphs[0]
        if len(description) > 200:
            # Find a good ending point
            cut_point = 180
            while cut_point < min(200, len(description)) and description[cut_point] not in ['.', '!', '?', ',', ';', ':']:
                cut_point += 1
            
            if cut_point < len(description):
                description = description[:cut_point + 1]
            else:
                description = description[:200]
                
        logger.info("Using first paragraph for site description")
        return description
    
    # Last resort: use the title or domain
    if soup.title and soup.title.string:
        title = soup.title.string.strip()
        logger.info("Using page title for site description")
        return title
    
    # Ultimate fallback
    logger.warning("No suitable content found for site description")
    return f"Website at {website_url}"

def is_generic_utility_url(url_path):
    """
    Check if the URL path is a generic utility page.
    Now VERY RELAXED to include all meaningful paths, only excluding truly non-content links.
    
    Args:
        url_path (str): The URL path to check
        
    Returns:
        bool: True if it's a non-content URL, False for all actual pages (including utility pages)
    """
    # Only exclude truly non-content links
    minimal_exclusions = [
        '#',  # Fragment only
        '?',  # Query only
        'javascript:',  # JavaScript links
        'mailto:',  # Email links
        'tel:',  # Telephone links
        'sms:',  # SMS links
    ]
    
    # Check if the path starts with any exclusion
    for exclusion in minimal_exclusions:
        if url_path.startswith(exclusion):
            return True
            
    # Allow ALL other paths, even utility pages like contact, about, terms, etc.
    # These can have meaningful content worth including
    return False

def is_generic_link_text(text):
    """
    Check if the link text is generic and not descriptive.
    
    Args:
        text (str): The link text to check
        
    Returns:
        bool: True if it's generic, False if it's descriptive
    """
    if not text:
        return True
        
    # Normalize text
    text = text.strip().lower()
    
    # List of generic link texts (universal for all websites)
    generic_texts = [
        'read more', 'learn more', 'click here', 'here', 'view details', 'details',
        'discover', 'explore', 'find out more', 'more', 'continue', 'continue reading',
        'view', 'view now', 'see more', 'see all', 'get started', 'sign up', 'register',
        'login', 'sign in', 'home', 'homepage', 'back', 'next', 'previous', 'submit',
        'send', 'go', 'go to', 'menu', 'navigation', 'search', 'help', 'support', 'faq',
        'team', 'news', 'events', 'resources', 'download', 'upload', 'share', 'follow',
        'subscribe', 'newsletter', 'feed', 'rss', 'sitemap', 'map', 'location', 'directions'
    ]
    
    # Check if text is in the generic list
    for generic in generic_texts:
        if text == generic:
            return True
            
    # Check if text is too short (and not in the whitelist)
    if len(text) < 10:  # Reduced from 15 to 10
        # Whitelist of short but specific terms (universal)
        short_whitelist = ['pricing', 'features', 'download', 'subscribe', 'demo', 'trial', 
                          'free', 'premium', 'pro', 'basic', 'advanced', 'api', 'docs', 
                          'guide', 'tutorial', 'example', 'sample', 'test', 'beta', 'alpha',
                          'blog', 'services', 'contact', 'about', 'careers', 'author', 'category']
        return not any(term in text for term in short_whitelist)
        
    return False

def extract_url_title(url_path):
    """
    Extract a title from the URL path when no better option is available.
    
    Args:
        url_path (str): The URL path
        
    Returns:
        str: A title derived from the URL path
    """
    # Get the last segment of the path
    path_parts = url_path.strip('/').split('/')
    if not path_parts or path_parts[-1] == '':
        if len(path_parts) > 1:
            # Try the second-to-last part if the last one is empty
            last_part = path_parts[-2]
        else:
            return "Homepage"
    else:
        last_part = path_parts[-1]
    
    # Remove file extensions if present
    if '.' in last_part:
        last_part = last_part.split('.')[0]
    
    # Remove query parameters if present
    if '?' in last_part:
        last_part = last_part.split('?')[0]
    
    # Remove common URL slugs and IDs
    last_part = re.sub(r'^id-\d+', '', last_part)
    last_part = re.sub(r'^post-\d+', '', last_part)
    last_part = re.sub(r'^page-\d+', '', last_part)
    
    # Replace hyphens, underscores, and plus signs with spaces
    title = last_part.replace('-', ' ').replace('_', ' ').replace('+', ' ')
    
    # Clean up the title
    title = re.sub(r'\s+', ' ', title).strip()
    
    # Title case (capitalize first letter of each word)
    if title:
        title = ' '.join(word.capitalize() for word in title.split())
        
        # Identify common pages and make them more descriptive (universal)
        lower_title = title.lower()
        if lower_title == 'contact':
            title = 'Contact Us Page'
        elif lower_title == 'about':
            title = 'About Us Page'
        elif lower_title == 'privacy':
            title = 'Privacy Policy'
        elif lower_title == 'terms':
            title = 'Terms of Service'
        elif lower_title == 'faq':
            title = 'FAQ Page'
        elif lower_title == 'blog':
            title = 'Blog Page'
        elif lower_title == 'news':
            title = 'News Page'
        elif lower_title == 'services':
            title = 'Services Page'
        elif lower_title == 'products':
            title = 'Products Page'
        elif lower_title == 'pricing':
            title = 'Pricing Page'
        elif lower_title == 'features':
            title = 'Features Page'
        elif lower_title == 'help':
            title = 'Help & Support Page'
        elif lower_title == 'support':
            title = 'Support Page'
        elif lower_title == 'team':
            title = 'Team Page'
        elif lower_title == 'careers':
            title = 'Careers Page'
    
    return title if title else "Homepage"

def get_structured_data_title(soup, a_tag):
    """
    Look for structured data titles in the vicinity of the link.
    
    Args:
        soup (BeautifulSoup): The parsed HTML
        a_tag (BeautifulSoup.Tag): The <a> tag
        
    Returns:
        str or None: A title from structured data if found
    """
    # Try to find a parent with itemscope or itemtype attributes
    item_parent = a_tag.find_parent(attrs={"itemscope": True}) or a_tag.find_parent(attrs={"itemtype": True})
    
    if item_parent:
        # Look for common schema.org title properties
        for prop in ["name", "headline", "title"]:
            item_prop = item_parent.find(attrs={"itemprop": prop})
            if item_prop:
                if item_prop.get("content"):
                    return item_prop.get("content")
                else:
                    text = item_prop.get_text(strip=True)
                    if text:
                        return text
    
    # Look for Open Graph title
    og_title = soup.find("meta", attrs={"property": "og:title"})
    if og_title and og_title.get("content"):
        return og_title.get("content")
        
    # Look for Twitter title
    twitter_title = soup.find("meta", attrs={"name": "twitter:title"})
    if twitter_title and twitter_title.get("content"):
        return twitter_title.get("content")
    
    return None

def get_link_title(soup, a_tag, full_url):
    """
    Extract the most descriptive title for a link using multiple advanced strategies.
    Enhanced to better prioritize content block titles for all types of websites.
    
    Args:
        soup (BeautifulSoup): The full page soup
        a_tag (BeautifulSoup.Tag): The <a> tag
        full_url (str): The full URL of the link
        
    Returns:
        str: The most descriptive title for the link
    """
    parsed_url = urlparse(full_url)
    link_title = None
    
    # Track attempts for logging
    attempts = []
    
    # Attempt 1: title attribute (high priority)
    if a_tag.get('title'):
        title = a_tag.get('title').strip()
        if title and len(title) > 5:
            attempts.append(f"Used title attribute: '{title}'")
            return title
        else:
            attempts.append(f"Title attribute too short: '{title}'")
    else:
        attempts.append("No title attribute")
    
    # NEW: Attempt 1.5: Direct Link Heading/Strong Text
    # Check if the link itself contains a heading or strong tag
    inner_heading = a_tag.find(['h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'strong', 'b'])
    if inner_heading:
        heading_text = inner_heading.get_text(strip=True)
        if heading_text and len(heading_text) > 10 and not is_generic_link_text(heading_text):
            attempts.append(f"Used inner heading/strong text: '{heading_text}'")
            return heading_text
        else:
            attempts.append(f"Inner heading/strong text insufficient: '{heading_text}'")
    else:
        attempts.append("No inner heading/strong text")
    
    # NEW: Attempt 1.8: Check if link is INSIDE a heading tag
    parent_heading = a_tag.find_parent(['h1', 'h2', 'h3', 'h4', 'h5', 'h6'])
    if parent_heading:
        heading_text = parent_heading.get_text(strip=True)
        if heading_text and len(heading_text) > 10 and not is_generic_link_text(heading_text):
            attempts.append(f"Used parent heading text: '{heading_text}'")
            return heading_text
        else:
            attempts.append(f"Parent heading text insufficient: '{heading_text}'")
    else:
        attempts.append("No parent heading")
    
    # Attempt 2: Link text content (if substantive)
    link_text = a_tag.get_text(strip=True)
    if link_text and len(link_text) > 15 and not is_generic_link_text(link_text):
        attempts.append(f"Used link text: '{link_text}'")
        return link_text
    else:
        attempts.append(f"Link text insufficient: '{link_text}'")
    
    # NEW: Attempt 2.5: Parent Container Title (critical for card/article layouts)
    # Match common content block classes with flexible regex for any website
    container = a_tag.find_parent(class_=lambda c: c and any(
        re.search(r'(post|card|entry|tool|service|feature|product|article|widget|item|content|text|body|main)', c) 
        for c in c.split()
    ))
    
    if container:
        # Try to find a heading within the container
        container_heading = container.find(['h1', 'h2', 'h3', 'h4', 'h5', 'h6'])
        if container_heading:
            heading_text = container_heading.get_text(strip=True)
            if heading_text and len(heading_text) > 10 and not is_generic_link_text(heading_text):
                attempts.append(f"Used heading in content container: '{heading_text}'")
                return heading_text
            else:
                attempts.append(f"Heading in content container insufficient: '{heading_text}'")
        
        # Try to find strong/emphasized text that might be a title
        strong_text = container.find(['strong', 'b', 'em'])
        if strong_text:
            text = strong_text.get_text(strip=True)
            if text and len(text) > 10 and not is_generic_link_text(text):
                attempts.append(f"Used strong text in content container: '{text}'")
                return text
            else:
                attempts.append(f"Strong text in content container insufficient: '{text}'")
                
        # Look for spans or divs with title-like classes
        title_elements = container.find_all(class_=lambda c: c and any(
            title_class in c.split() for title_class in ['title', 'name', 'heading', 'header']
        ))
        for title_elem in title_elements:
            text = title_elem.get_text(strip=True)
            if text and len(text) > 10 and not is_generic_link_text(text):
                attempts.append(f"Used title element in content container: '{text}'")
                return text
    else:
        attempts.append("No suitable content container found")
    
    # Attempt 3: Nearby Headings (H1-H6)
    
    # 3.1: Check previous sibling headings
    prev_heading = a_tag.find_previous_sibling(['h1', 'h2', 'h3', 'h4', 'h5', 'h6'])
    if prev_heading:
        heading_text = prev_heading.get_text(strip=True)
        if heading_text and len(heading_text) > 5:
            attempts.append(f"Used previous sibling heading: '{heading_text}'")
            return heading_text
        else:
            attempts.append(f"Previous sibling heading insufficient: '{heading_text}'")
    else:
        attempts.append("No previous sibling heading")
    
    # 3.2: Check next sibling headings
    next_heading = a_tag.find_next_sibling(['h1', 'h2', 'h3', 'h4', 'h5', 'h6'])
    if next_heading:
        heading_text = next_heading.get_text(strip=True)
        if heading_text and len(heading_text) > 5:
            attempts.append(f"Used next sibling heading: '{heading_text}'")
            return heading_text
        else:
            attempts.append(f"Next sibling heading insufficient: '{heading_text}'")
    else:
        attempts.append("No next sibling heading")
    
    # 3.3: Check parent's previous sibling headings
    parent = a_tag.parent
    if parent:
        parent_prev_heading = parent.find_previous_sibling(['h1', 'h2', 'h3', 'h4', 'h5', 'h6'])
        if parent_prev_heading:
            heading_text = parent_prev_heading.get_text(strip=True)
            if heading_text and len(heading_text) > 5:
                attempts.append(f"Used parent's previous sibling heading: '{heading_text}'")
                return heading_text
            else:
                attempts.append(f"Parent's previous sibling heading insufficient: '{heading_text}'")
        else:
            attempts.append("No parent's previous sibling heading")
    
    # 3.4: Check headings within the parent
    if parent:
        parent_heading = parent.find(['h1', 'h2', 'h3', 'h4', 'h5', 'h6'])
        if parent_heading:
            heading_text = parent_heading.get_text(strip=True)
            if heading_text and len(heading_text) > 5:
                attempts.append(f"Used heading within parent: '{heading_text}'")
                return heading_text
            else:
                attempts.append(f"Heading within parent insufficient: '{heading_text}'")
        else:
            attempts.append("No heading within parent")
    
    # Attempt 4: Parent Link Title (Already moved as Attempt 2.5 to higher priority)
    
    # Attempt 5: Schema Markup (Structured Data)
    structured_title = get_structured_data_title(soup, a_tag)
    if structured_title:
        attempts.append(f"Used structured data title: '{structured_title}'")
        return structured_title
    else:
        attempts.append("No structured data title found")
    
    # Attempt 6: URL Path to Title Heuristic
    url_title = extract_url_title(parsed_url.path)
    if url_title:
        attempts.append(f"Used URL-derived title: '{url_title}'")
        return url_title
    else:
        attempts.append("Could not derive title from URL")
    
    # Final fallback - use the link text even if generic
    if link_text:
        attempts.append(f"Fallback to link text: '{link_text}'")
        return link_text
    
    # Ultimate fallback
    attempts.append("All attempts failed, using generic fallback")
    logger.debug(f"Title extraction attempts for {full_url}: {', '.join(attempts)}")
    return f"Page at {parsed_url.path or '/'}"

def extract_internal_links(soup, website_url):
    """
    Extract internal links from the parsed HTML and sitemap.
    
    Args:
        soup (BeautifulSoup): The parsed HTML
        website_url (str): The base website URL
        
    Returns:
        list: List of internal links with descriptions and URLs
    """
    internal_links = []
    parsed_base_url = urlparse(website_url)
    base_domain = parsed_base_url.netloc
    
    # Track unique URLs to avoid duplicates
    unique_urls = set()
    
    # First, get URLs from sitemap
    sitemap_urls = get_sitemap_urls(website_url)
    logger.info(f"Found {len(sitemap_urls)} URLs from sitemap")
    
    # Log some example URLs for debugging
    if sitemap_urls:
        logger.info(f"Sample sitemap URLs: {sitemap_urls[:5]}")
        logger.info(f"Total sitemap URLs to process: {len(sitemap_urls)}")
    
    # Add sitemap URLs to our list (excluding images)
    for sitemap_url in sitemap_urls:
        # Skip image URLs as they're not content pages
        if any(ext in sitemap_url.lower() for ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.svg', '.ico']):
            continue
            
        if sitemap_url not in unique_urls:
            unique_urls.add(sitemap_url)
            # Extract title from URL path for sitemap URLs
            url_title = extract_url_title(urlparse(sitemap_url).path)
            internal_links.append({
                "description": url_title,
                "url": sitemap_url
            })
    
    # Find all links in the page
    for a_tag in soup.find_all('a', href=True):
        href = a_tag.get('href')
        
        # Skip empty links, anchors, and non-HTTP schemes
        if not href or href.startswith(('javascript:', 'mailto:', 'tel:')):
            continue
        
        # Construct absolute URL
        full_url = urljoin(website_url, href)
        parsed_url = urlparse(full_url)
        
        # Skip external links and ensure it's HTTP/HTTPS
        if parsed_url.netloc != base_domain or not parsed_url.scheme.startswith(('http', 'https')):
            continue
        
        # Skip if we've already processed this URL
        if full_url in unique_urls:
            continue
        
        unique_urls.add(full_url)
        
        # Get link title using the enhanced function
        link_title = get_link_title(soup, a_tag, full_url)
        
        internal_links.append({
            "description": link_title,
            "url": full_url
        })
    
    # Count filtered sitemap URLs
    filtered_sitemap_urls = [url for url in sitemap_urls if any(ext in url.lower() for ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.svg', '.ico'])]
    content_sitemap_urls = [url for url in sitemap_urls if not any(ext in url.lower() for ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.svg', '.ico'])]
    
    logger.info(f"Total internal links found: {len(internal_links)} (HTML: {len(internal_links) - len(content_sitemap_urls)}, Sitemap: {len(content_sitemap_urls)})")
    logger.info(f"Sitemap filtering: {len(sitemap_urls)} total URLs, {len(filtered_sitemap_urls)} images filtered out, {len(content_sitemap_urls)} content URLs kept")
    
    # Log detailed breakdown
    content_urls = [link for link in internal_links if any(path in link['url'] for path in ['/blog/', '/article/', '/post/', '/news/', '/content/'])]
    logger.info(f"Content URLs found: {len(content_urls)}")
    
    return internal_links

def fetch_page_and_extract_full_content(page_url, link_title=None):
    """
    Fetches a web page and extracts its main content without LLM summarization.
    This version aims to get as much relevant text as possible.
    
    Args:
        page_url (str): The URL of the page to fetch
        link_title (str, optional): The title of the link (for context in error messages)
        
    Returns:
        dict: Dictionary containing content and metadata, or error message string.
    """
    try:
        if not check_robots_txt(page_url):
            return f"Respecting robots.txt: Not allowed to access {page_url}"
        
        logger.info(f"Fetching full content for page: {page_url}")
        response = requests.get(page_url, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Extract metadata
        metadata = {}
        
        # Get canonical URL
        canonical = soup.find('link', rel='canonical')
        metadata['canonical'] = canonical.get('href') if canonical else page_url
        
        # Get last modified date
        last_modified = response.headers.get('Last-Modified')
        if last_modified:
            # Convert to a more readable format
            try:
                last_modified_dt = parsedate_to_datetime(last_modified)
                metadata['last_modified'] = last_modified_dt.strftime('%Y-%m-%d')
            except:
                metadata['last_modified'] = last_modified
        else:
            metadata['last_modified'] = 'Unknown'
        
        # Get crawl date (current date)
        metadata['crawl_date'] = datetime.now().strftime('%Y-%m-%d')
        
        # Get HTTP status
        metadata['http_status'] = response.status_code
        
        # Get fetch status
        metadata['fetch_status'] = 'ok'
        
        # Detect pagination information
        pagination_info = detect_pagination_info(soup, page_url)
        if pagination_info['has_pagination']:
            metadata['pagination'] = pagination_info
        
        # Remove likely irrelevant elements
        for element in soup.find_all(['nav', 'footer', 'aside', 'style', 'script', 'noscript', 'header', 'form', 'img', 'svg', 'iframe']):
            element.decompose()
        
        # Use markdown preservation for content extraction
        full_page_content = extract_main_content_with_markdown(soup)
        
        # Calculate word count
        word_count = len(full_page_content.split()) if full_page_content else 0
        metadata['word_count'] = word_count
        
        # Extract tags (try to find meta keywords or other tag indicators)
        tags = []
        
        # Try meta keywords
        meta_keywords = soup.find('meta', attrs={'name': 'keywords'})
        if meta_keywords and meta_keywords.get('content'):
            tags.extend([tag.strip() for tag in meta_keywords.get('content').split(',') if tag.strip()])
        
        # Try to extract tags from common tag elements
        tag_elements = soup.find_all(['span', 'a', 'div'], class_=lambda c: c and any(tag_word in c.lower() for tag_word in ['tag', 'category', 'label']))
        for tag_elem in tag_elements[:5]:  # Limit to first 5 tags
            tag_text = tag_elem.get_text(strip=True)
            if tag_text and len(tag_text) < 50 and tag_text not in tags:
                tags.append(tag_text)
        
        metadata['tags'] = tags[:10] if tags else []  # Limit to 10 tags
        
        if full_page_content:
            return {
                'content': full_page_content,
                'metadata': metadata
            }
        else:
            return f"No substantial content extracted from {page_url}"
        
    except requests.exceptions.Timeout:
        logger.error(f"Timeout error fetching full content for {page_url}")
        return f"Timeout accessing: {page_url}"
    except requests.exceptions.ConnectionError:
        logger.error(f"Connection error fetching full content for {page_url}")
        return f"Connection error: {page_url}"
    except requests.exceptions.HTTPError as e:
        status_code = e.response.status_code if e.response else "unknown"
        logger.error(f"HTTP error {status_code} fetching full content for {page_url}")
        return f"HTTP error {status_code}: {page_url}"
    except Exception as e:
        logger.error(f"Error fetching/extracting full content for {page_url}: {str(e)}")
        return f"Error fetching content: {page_url} - {str(e)}"

def format_llms_full_text(website_url, site_description, successful_sections, failed_sections):
    """
    Format the llms-full.txt content with separate sections for successful and failed pages.
    
    Args:
        website_url (str): The main website URL
        site_description (str): The site description
        successful_sections (list): List of dictionaries with 'title', 'url', and 'content' keys
        failed_sections (list): List of dictionaries with 'title', 'url', and 'error' keys
        
    Returns:
        str: Formatted llms-full.txt content
    """
    parsed_url = urlparse(website_url)
    domain_name = parsed_url.netloc
    
    llms_full_text = f"# {domain_name} llms-full.txt\n\n"
    llms_full_text += f"Website Description: {site_description}\n\n"
    
    # Add global start marker
    llms_full_text += "--- Start Full Website Content ---\n\n"
    
    # Add successful pages section
    if successful_sections:
        
        # Sort by title for consistent output
        sorted_successful = sorted(successful_sections, key=lambda x: x.get("title", "").lower())
        
        for section in sorted_successful:
            title = section.get("title", "No Title Available")
            url = section.get("url", "No URL Available")
            content = section.get("content", "No content extracted for this page.")
            metadata = section.get("metadata", {})
            
            llms_full_text += f"## Page Title: {title}\n"
            llms_full_text += f"URL: {url}\n"
            
            # Add metadata if available
            if metadata:
                canonical = metadata.get('canonical', url)
                last_modified = metadata.get('last_modified', 'Unknown')
                crawl_date = metadata.get('crawl_date', 'Unknown')
                http_status = metadata.get('http_status', 'Unknown')
                fetch_status = metadata.get('fetch_status', 'Unknown')
                word_count = metadata.get('word_count', 0)
                tags = metadata.get('tags', [])
                pagination = metadata.get('pagination', {})
                
                llms_full_text += f"Canonical: {canonical}\n"
                llms_full_text += f"Last-Modified: {last_modified}\n"
                llms_full_text += f"Crawl-Date: {crawl_date}\n"
                llms_full_text += f"HTTP-Status: {http_status}\n"
                llms_full_text += f"Fetch-Status: {fetch_status}\n"
                llms_full_text += f"Word-Count: {word_count}\n"
                
                if tags:
                    tags_str = ', '.join(tags)
                    llms_full_text += f"Tags: {tags_str}\n"
            
            llms_full_text += "\n"
            llms_full_text += f"{content}\n\n"
            
            # Add pagination note if available
            if metadata and metadata.get('pagination', {}).get('pagination_note'):
                pagination_note = metadata['pagination']['pagination_note']
                llms_full_text += f"> Pagination: {pagination_note}\n\n"
            
            llms_full_text += "---\n\n"  # Separator between pages for full content option
    
    # Add failed pages section
    if failed_sections:
        llms_full_text += "--- Start Failed Pages ---\n\n"
        
        # Sort by title for consistent output
        sorted_failed = sorted(failed_sections, key=lambda x: x.get("title", "").lower())
        
        for section in sorted_failed:
            title = section.get("title", "No Title Available")
            url = section.get("url", "No URL Available")
            error = section.get("error", "Unknown error occurred.")
            
            llms_full_text += f"## Page Title: {title}\n"
            llms_full_text += f"URL: {url}\n"
            
            # Try to extract HTTP status from error message
            http_status = "Unknown"
            fetch_status = "error"
            error_note = error
            
            # Check if error contains HTTP status code
            import re
            status_match = re.search(r'HTTP error (\d+)', error)
            if status_match:
                status_code = int(status_match.group(1))
                http_status = f"{status_code} {get_http_status_text(status_code)}"
                fetch_status = f"error {status_code}"
                error_note = f"Page returned {status_code} {get_http_status_text(status_code)} at crawl time; exclude from listing, include in error log only."
            
            llms_full_text += f"Canonical: {url}\n"
            llms_full_text += f"Last-Modified: Unknown\n"
            llms_full_text += f"Crawl-Date: {datetime.now().strftime('%Y-%m-%d')}\n"
            llms_full_text += f"HTTP-Status: {http_status}\n"
            llms_full_text += f"Fetch-Status: {fetch_status}\n"
            llms_full_text += f"Word-Count: 0\n"
            llms_full_text += f"Error-Note: {error_note}\n\n"
            llms_full_text += "---\n\n"
        
        llms_full_text += "--- End Failed Pages ---\n\n"
    
    # Add summary statistics
    total_pages = len(successful_sections) + len(failed_sections)
    success_rate = (len(successful_sections) / total_pages * 100) if total_pages > 0 else 0
    
    llms_full_text += f"## Summary\n"
    llms_full_text += f"- Total pages discovered: {total_pages}\n"
    llms_full_text += f"- Successfully processed: {len(successful_sections)}\n"
    llms_full_text += f"- Failed to process: {len(failed_sections)}\n"
    llms_full_text += f"- Success rate: {success_rate:.1f}%\n\n"
    
    # Add global end marker
    llms_full_text += "--- End Full Website Content ---\n"
    
    return llms_full_text

def get_http_status_text(status_code):
    """
    Get human-readable text for HTTP status codes.
    
    Args:
        status_code (int): HTTP status code
        
    Returns:
        str: Human-readable status text
    """
    status_texts = {
        200: "OK",
        201: "Created",
        202: "Accepted",
        204: "No Content",
        301: "Moved Permanently",
        302: "Found",
        304: "Not Modified",
        307: "Temporary Redirect",
        308: "Permanent Redirect",
        400: "Bad Request",
        401: "Unauthorized",
        403: "Forbidden",
        404: "Not Found",
        405: "Method Not Allowed",
        408: "Request Timeout",
        409: "Conflict",
        410: "Gone",
        429: "Too Many Requests",
        500: "Internal Server Error",
        501: "Not Implemented",
        502: "Bad Gateway",
        503: "Service Unavailable",
        504: "Gateway Timeout",
        505: "HTTP Version Not Supported"
    }
    
    return status_texts.get(status_code, f"Unknown Status {status_code}")

def detect_pagination_info(soup, current_url):
    """
    Detect pagination information on the current page.
    
    Args:
        soup (BeautifulSoup): The parsed HTML
        current_url (str): The current page URL
        
    Returns:
        dict: Pagination information including next/prev links and page count
    """
    pagination_info = {
        'has_pagination': False,
        'current_page': None,
        'total_pages': None,
        'next_page': None,
        'prev_page': None,
        'pagination_note': None
    }
    
    try:
        # Common pagination selectors
        pagination_selectors = [
            '.pagination', '.pager', '.page-numbers', '.page-nav', 
            '.paginate', '.page-links', '.wp-pagenavi', '.pagenavi',
            '[class*="pagination"]', '[class*="pager"]', '[class*="page-nav"]'
        ]
        
        pagination_container = None
        for selector in pagination_selectors:
            container = soup.select_one(selector)
            if container:
                pagination_container = container
                break
        
        if not pagination_container:
            # Look for common pagination text patterns
            pagination_text_patterns = [
                r'page\s+\d+\s+of\s+\d+',
                r'\d+\s+of\s+\d+\s+pages?',
                r'showing\s+\d+\s*-\s*\d+\s+of\s+\d+',
                r'results?\s+\d+\s*-\s*\d+\s+of\s+\d+'
            ]
            
            page_text = soup.get_text(strip=True).lower()
            for pattern in pagination_text_patterns:
                if re.search(pattern, page_text, re.IGNORECASE):
                    pagination_info['has_pagination'] = True
                    pagination_info['pagination_note'] = "Pagination detected in text but no structured navigation found"
                    break
            
            return pagination_info
        
        pagination_info['has_pagination'] = True
        
        # Extract current page and total pages
        current_page_elem = pagination_container.select_one('.current, .active, [aria-current="page"]')
        if current_page_elem:
            current_page_text = current_page_elem.get_text(strip=True)
            if current_page_text.isdigit():
                pagination_info['current_page'] = int(current_page_text)
        
        # Try to find total pages
        page_links = pagination_container.select('a[href]')
        page_numbers = []
        for link in page_links:
            link_text = link.get_text(strip=True)
            if link_text.isdigit():
                page_numbers.append(int(link_text))
        
        if page_numbers:
            pagination_info['total_pages'] = max(page_numbers)
        
        # Find next and previous page links
        from urllib.parse import urljoin
        
        # Next page patterns
        next_patterns = ['next', '>', '→', 'next page', 'more']
        for link in page_links:
            link_text = link.get_text(strip=True).lower()
            if any(pattern in link_text for pattern in next_patterns):
                pagination_info['next_page'] = urljoin(current_url, link.get('href'))
                break
        
        # Previous page patterns
        prev_patterns = ['prev', 'previous', '<', '←', 'prev page', 'back']
        for link in page_links:
            link_text = link.get_text(strip=True).lower()
            if any(pattern in link_text for pattern in prev_patterns):
                pagination_info['prev_page'] = urljoin(current_url, link.get('href'))
                break
        
        # Generate pagination note
        if pagination_info['current_page'] and pagination_info['total_pages']:
            pagination_info['pagination_note'] = f"Page {pagination_info['current_page']} of {pagination_info['total_pages']} pages detected"
        elif pagination_info['has_pagination']:
            pagination_info['pagination_note'] = "Pagination detected - additional pages may be available"
        
    except Exception as e:
        logger.error(f"Error detecting pagination for {current_url}: {str(e)}")
    
    return pagination_info



def process_link_with_summary(link, base_url):
    """
    Process a single link to get its summary.
    This function is designed to be used with concurrent.futures.
    
    Args:
        link (dict): Dictionary containing the link data
        base_url (str): The base URL of the website
        
    Returns:
        dict: The link data with added summary
    """
    url = link["url"]
    title = link["description"]
    
    try:
        # Get the summary
        summary = get_page_summary(url, title)
        
        # Return the full link data
        return {
            "summary": summary,
            "url": url,
            "title": title
        }
    except Exception as e:
        logger.error(f"Error processing link {url}: {str(e)}")
        return {
            "summary": f"Error summarizing: {url}",
            "url": url,
            "title": title
        }

@app.route('/')
def index():
    """Render the main page."""
    return render_template('index.html')

@app.route('/health')
def health_check():
    """
    Health check endpoint for monitoring application status.
    Returns basic application information and status.
    """
    try:
        # Check if OpenAI API key is configured
        openai_status = "configured" if OPENAI_API_KEY else "not_configured"
        
        # Basic system checks
        health_status = {
            "status": "healthy",
            "timestamp": datetime.now().isoformat(),
            "version": "1.0.0",
            "openai_api": openai_status,
            "environment": {
                "request_timeout": REQUEST_TIMEOUT,
                "concurrent_workers": CONCURRENT_WORKERS,
                "api_call_delay": API_CALL_DELAY
            },
            "uptime": "running"  # In a production environment, you'd track actual uptime
        }
        
        return jsonify(health_status), 200
        
    except Exception as e:
        logger.error(f"Health check failed: {str(e)}")
        return jsonify({
            "status": "unhealthy",
            "timestamp": datetime.now().isoformat(),
            "error": str(e)
        }), 500

@app.route('/generate_llm_text', methods=['POST'])
def generate_llm_text():
    start_time = time.time()
    try:
        data = request.get_json()
        website_url = data.get('websiteUrl')
        output_type = data.get('outputType', 'llms_txt')  # Get the new outputType, default to 'llms_txt'

        if not website_url:
            error_msg = "Website URL is required"
            log_request(website_url, output_type, False, error_msg, time.time() - start_time)
            return jsonify({"error": error_msg}), 400

        # Use enhanced URL validation
        is_valid, validation_error = validate_url(website_url)
        if not is_valid:
            log_request(website_url, output_type, False, validation_error, time.time() - start_time)
            return jsonify({"error": validation_error}), 400

        logger.info(f"Received request for URL: {website_url} with output type: {output_type}")

        # Check robots.txt for the main website URL
        if not check_robots_txt(website_url):
            return jsonify({"error": f"Access to {website_url} is disallowed by robots.txt"}), 403

        # Fetch the main page content
        try:
            logger.info(f"Fetching main page: {website_url}")
            response = requests.get(website_url, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()  # Raise an HTTPError for bad responses (4xx or 5xx)
        except requests.exceptions.Timeout:
            return jsonify({"error": f"Timeout accessing: {website_url}"}), 504
        except requests.exceptions.ConnectionError:
            return jsonify({"error": f"Connection error: {website_url}"}), 503
        except requests.exceptions.HTTPError as e:
            return jsonify({"error": f"HTTP error {e.response.status_code} for {website_url}"}), e.response.status_code
        except Exception as e:
            return jsonify({"error": f"Error fetching main page: {str(e)}"}), 500

        soup = BeautifulSoup(response.text, 'html.parser')

        site_description = extract_site_description(soup, website_url)
        internal_links = extract_internal_links(soup, website_url)
        valid_links = [
            link for link in internal_links
            if not is_generic_utility_url(urlparse(link['url']).path) and
               not is_generic_link_text(link['description'])
        ]
        logger.info(f"Found {len(valid_links)} valid internal links after filtering.")
        
        # Log detailed breakdown of valid links
        content_links = [link for link in valid_links if any(path in link['url'] for path in ['/blog/', '/article/', '/post/', '/news/', '/content/'])]
        logger.info(f"Valid content links to process: {len(content_links)}")
        logger.info(f"Total valid links to process: {len(valid_links)}")

        if output_type == 'llms_txt':
            logger.info("Generating LLM Text (summarized)")
            successful_links = []
            failed_links = []
            with concurrent.futures.ThreadPoolExecutor(max_workers=CONCURRENT_WORKERS) as executor:
                future_to_link = {executor.submit(get_page_summary, link["url"], link["description"]): link for link in valid_links}
                total_links = len(valid_links)
                logger.info(f"Starting to process {total_links} links with {CONCURRENT_WORKERS} workers")
                
                for i, future in enumerate(concurrent.futures.as_completed(future_to_link)):
                    if (i + 1) % 10 == 0:  # Log progress every 10 processed links
                        logger.info(f"Processed {i + 1}/{total_links} links ({(i + 1)/total_links*100:.1f}%)")
                    link = future_to_link[future]
                    try:
                        summary = future.result()
                        successful_links.append({
                            "summary": summary,
                            "url": link["url"],
                            "title": link["description"]
                        })
                    except Exception as exc:
                        logger.error(f"Error processing link {link['url']}: {str(exc)}")
                        failed_links.append({
                            "url": link["url"],
                            "title": link["description"],
                            "error": str(exc)
                        })
            
            logger.info("Formatting llms.txt content")
            llms_text = format_llms_text(website_url, site_description, successful_links, failed_links)
            
            logger.info("Successfully generated llms.txt content")
            logger.info(f"Final processing summary: {len(successful_links)} successful, {len(failed_links)} failed out of {len(valid_links)} total links")
            processing_time = time.time() - start_time
            total_words = sum(len(link.get("summary", "").split()) for link in successful_links)
            log_request(website_url, output_type, True, None, processing_time, total_words)
            return jsonify({
                "llms_text": llms_text,
                "site_description": site_description,
                "successful_links": successful_links,
                "failed_links": failed_links
            })

        elif output_type == 'llms_full_txt':
            logger.info("Generating LLM Full Text (full content)")
            successful_sections = []
            failed_sections = []
            with concurrent.futures.ThreadPoolExecutor(max_workers=CONCURRENT_WORKERS) as executor:
                # Use partial to pass fetch_page_and_extract_full_content for each link
                fetch_and_extract_func = partial(fetch_page_and_extract_full_content)  # This new function must be defined below
                future_to_link = {executor.submit(fetch_and_extract_func, link["url"], link["description"]): link for link in valid_links}

                for i, future in enumerate(concurrent.futures.as_completed(future_to_link)):
                    link = future_to_link[future]
                    try:
                        result = future.result()
                        if isinstance(result, dict) and 'content' in result:
                            # New format with metadata
                            successful_sections.append({
                                "title": link["description"],
                                "url": link["url"],
                                "content": result['content'],
                                "metadata": result['metadata']
                            })
                        else:
                            # Old format (string) or error message
                            successful_sections.append({
                                "title": link["description"],
                                "url": link["url"],
                                "content": result
                            })
                    except Exception as exc:
                        logger.error(f"Error processing full content for link {link['url']}: {str(exc)}")
                        failed_sections.append({
                            "title": link["description"],
                            "url": link["url"],
                            "error": str(exc)
                        })
            
            logger.info("Formatting llms-full.txt content")
            llms_full_text_output = format_llms_full_text(website_url, site_description, successful_sections, failed_sections)  # This new function must be defined below
            
            logger.info("Successfully generated llms-full.txt content")
            processing_time = time.time() - start_time
            total_words = sum(len(section.get("content", "").split()) for section in successful_sections)
            log_request(website_url, output_type, True, None, processing_time, total_words)
            return jsonify({
                "llms_full_text": llms_full_text_output,
                "site_description": site_description,
                "successful_sections": successful_sections,
                "failed_sections": failed_sections
            })

        elif output_type == 'llms_both':
            logger.info("Generating both LLM Text and Full Text")
            
            # Generate summarized content
            successful_summary_links = []
            failed_summary_links = []
            with concurrent.futures.ThreadPoolExecutor(max_workers=CONCURRENT_WORKERS) as executor:
                future_to_link = {executor.submit(get_page_summary, link["url"], link["description"]): link for link in valid_links}
                for i, future in enumerate(concurrent.futures.as_completed(future_to_link)):
                    link = future_to_link[future]
                    try:
                        summary = future.result()
                        successful_summary_links.append({
                            "summary": summary,
                            "url": link["url"],
                            "title": link["description"]
                        })
                    except Exception as exc:
                        logger.error(f"Error processing link {link['url']}: {str(exc)}")
                        failed_summary_links.append({
                            "url": link["url"],
                            "title": link["description"],
                            "error": str(exc)
                        })
            
            # Generate full content
            successful_full_sections = []
            failed_full_sections = []
            with concurrent.futures.ThreadPoolExecutor(max_workers=CONCURRENT_WORKERS) as executor:
                fetch_and_extract_func = partial(fetch_page_and_extract_full_content)
                future_to_link = {executor.submit(fetch_and_extract_func, link["url"], link["description"]): link for link in valid_links}

                for i, future in enumerate(concurrent.futures.as_completed(future_to_link)):
                    link = future_to_link[future]
                    try:
                        result = future.result()
                        if isinstance(result, dict) and 'content' in result:
                            # New format with metadata
                            successful_full_sections.append({
                                "title": link["description"],
                                "url": link["url"],
                                "content": result['content'],
                                "metadata": result['metadata']
                            })
                        else:
                            # Old format (string) or error message
                            successful_full_sections.append({
                                "title": link["description"],
                                "url": link["url"],
                                "content": result
                            })
                    except Exception as exc:
                        logger.error(f"Error processing full content for link {link['url']}: {str(exc)}")
                        failed_full_sections.append({
                            "title": link["description"],
                            "url": link["url"],
                            "error": str(exc)
                        })
            
            logger.info("Formatting both llms.txt and llms-full.txt content")
            llms_text = format_llms_text(website_url, site_description, successful_summary_links, failed_summary_links)
            llms_full_text_output = format_llms_full_text(website_url, site_description, successful_full_sections, failed_full_sections)
            
            logger.info("Successfully generated both content types")
            processing_time = time.time() - start_time
            total_words = sum(len(link.get("summary", "").split()) for link in successful_summary_links) + \
                         sum(len(section.get("content", "").split()) for section in successful_full_sections)
            log_request(website_url, output_type, True, None, processing_time, total_words)
            return jsonify({
                "llms_text": llms_text,
                "llms_full_text": llms_full_text_output,
                "site_description": site_description,
                "successful_summary_links": successful_summary_links,
                "failed_summary_links": failed_summary_links,
                "successful_full_sections": successful_full_sections,
                "failed_full_sections": failed_full_sections
            })

        else:
            logger.warning(f"Invalid outputType received: {output_type}")
            error_msg = "Invalid outputType specified"
            log_request(website_url, output_type, False, error_msg, time.time() - start_time)
            return jsonify({"error": error_msg}), 400
        
    except requests.exceptions.RequestException as e:
        error_message = f"Failed to fetch website: {str(e)}"
        logger.error(f"Request error: {error_message}")
        log_request(website_url, output_type, False, error_message, time.time() - start_time)
        return jsonify({"error": error_message}), 500
    except Exception as e:
        error_message = f"Error processing website content: {str(e)}"
        logger.error(f"Processing error: {error_message}")
        log_request(website_url, output_type, False, error_message, time.time() - start_time)
        return jsonify({"error": error_message}), 500

def parse_sitemap(sitemap_url):
    """
    Parse sitemap.xml to extract all URLs.
    
    Args:
        sitemap_url (str): URL of the sitemap.xml file
        
    Returns:
        list: List of URLs from the sitemap
    """
    try:
        logger.info(f"Fetching sitemap: {sitemap_url}")
        response = requests.get(sitemap_url, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.content, 'xml')
        urls = []
        
        # Handle both sitemap index and regular sitemap
        if soup.find('sitemapindex'):
            # This is a sitemap index, get all sitemap URLs
            sitemaps = soup.find_all('sitemap')
            for sitemap in sitemaps:
                loc = sitemap.find('loc')
                if loc:
                    sub_urls = parse_sitemap(loc.text.strip())
                    urls.extend(sub_urls)
        else:
            # Regular sitemap, extract URLs
            url_elements = soup.find_all('url')
            for url_elem in url_elements:
                loc = url_elem.find('loc')
                if loc:
                    urls.append(loc.text.strip())
        
        logger.info(f"Found {len(urls)} URLs in sitemap")
        
        # Debug: Log URL types
        content_urls = [url for url in urls if any(path in url for path in ['/blog/', '/article/', '/post/', '/news/', '/content/'])]
        image_urls = [url for url in urls if any(ext in url.lower() for ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp'])]
        other_urls = [url for url in urls if not any(path in url for path in ['/blog/', '/article/', '/post/', '/news/', '/content/']) and not any(ext in url.lower() for ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp'])]
        
        logger.info(f"URL breakdown: {len(content_urls)} content URLs, {len(image_urls)} image URLs, {len(other_urls)} other URLs")
        if content_urls:
            logger.info(f"Sample content URLs: {content_urls[:3]}")
        if image_urls:
            logger.info(f"Sample image URLs: {image_urls[:3]}")
        
        return urls
        
    except Exception as e:
        logger.warning(f"Error parsing sitemap {sitemap_url}: {str(e)}")
        return []

def get_sitemap_urls(website_url):
    """
    Try to find and parse sitemap.xml for the given website.
    
    Args:
        website_url (str): The main website URL
        
    Returns:
        list: List of URLs from sitemap, or empty list if not found
    """
    parsed_url = urlparse(website_url)
    base_url = f"{parsed_url.scheme}://{parsed_url.netloc}"
    
    # Common sitemap locations
    sitemap_locations = [
        f"{base_url}/sitemap.xml",
        f"{base_url}/sitemap_index.xml",
        f"{base_url}/post-sitemap.xml",  # Add specific post sitemap
        f"{base_url}/sitemap/sitemap.xml",
        f"{base_url}/sitemaps/sitemap.xml"
    ]
    
    for sitemap_url in sitemap_locations:
        try:
            response = requests.head(sitemap_url, timeout=5)
            if response.status_code == 200:
                return parse_sitemap(sitemap_url)
        except:
            continue
    
    # Try robots.txt for sitemap location
    try:
        robots_url = f"{base_url}/robots.txt"
        response = requests.get(robots_url, timeout=5)
        if response.status_code == 200:
            for line in response.text.split('\n'):
                if line.lower().startswith('sitemap:'):
                    sitemap_url = line.split(':', 1)[1].strip()
                    return parse_sitemap(sitemap_url)
    except:
        pass
    
    # Try specific post-sitemap.xml if it's a blog/content site
    try:
        post_sitemap_url = f"{base_url}/post-sitemap.xml"
        response = requests.head(post_sitemap_url, timeout=5)
        if response.status_code == 200:
            logger.info(f"Found post-sitemap.xml at {post_sitemap_url}")
            return parse_sitemap(post_sitemap_url)
    except:
        pass
    
    return []

if __name__ == '__main__':
    logger.info("Starting LLM Text Generator application")
    app.run(debug=True) 