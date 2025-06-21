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

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

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
CONCURRENT_WORKERS = int(os.environ.get("CONCURRENT_WORKERS", 5))
# Delay between API calls in seconds (to avoid rate limiting)
API_CALL_DELAY = float(os.environ.get("API_CALL_DELAY", 0.5))

app = Flask(__name__)

def validate_url(url):
    """
    Validate if the provided URL is valid and safe to access.
    
    Args:
        url (str): The URL to validate
        
    Returns:
        tuple: (is_valid, error_message)
    """
    # Basic URL format validation
    if not url or not isinstance(url, str):
        return False, "URL is required and must be a string"
    
    # Check if URL starts with http:// or https://
    if not url.startswith(('http://', 'https://')):
        return False, "URL must start with http:// or https://"
    
    # Use validators library for comprehensive URL validation
    if not validators.url(url):
        return False, "Invalid URL format"
    
    # Parse URL to check components
    try:
        parsed_url = urlparse(url)
        # Verify netloc (domain) exists
        if not parsed_url.netloc:
            return False, "URL missing domain name"
        
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
        '.tool-description', '.product-description', '.page-content'
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
        for section_tag in ['section', 'div[class*="content"]', 'div[class*="article"]', 'div[class*="post"]']:
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

def clean_summary(summary, max_length=150):
    """
    Clean and truncate a summary to ensure it's concise and ends at a natural point.
    Improved to handle edge cases and ensure proper truncation at sentence/phrase boundaries.
    
    Args:
        summary (str): The summary to clean
        max_length (int): Maximum length for the summary
        
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
    
    # If it's within length limits, return as is
    if len(summary) <= max_length:
        return summary
    
    # Find the best point to cut the summary
    # Start looking from 30 chars before the max_length to ensure we find a good break
    safety_margin = 30
    cut_search_start = max(0, max_length - safety_margin)
    
    # First priority: Find a sentence end (period, exclamation, question mark)
    best_end = -1
    for i in range(cut_search_start, min(max_length, len(summary))):
        if summary[i] in ['.', '!', '?'] and (i+1 == len(summary) or summary[i+1] == ' '):
            best_end = i + 1
            break
    
    # If we found a good sentence end, use it
    if best_end > 0:
        return summary[:best_end].strip()
    
    # Second priority: Find a phrase break (comma, semicolon, colon)
    for i in range(cut_search_start, min(max_length, len(summary))):
        if summary[i] in [',', ';', ':'] and (i+1 == len(summary) or summary[i+1] == ' '):
            best_end = i + 1
            break
    
    # If we found a phrase break, use it
    if best_end > 0:
        return summary[:best_end].strip()
    
    # Third priority: Find a conjunction or preposition
    conjunctions = [' and ', ' but ', ' or ', ' nor ', ' for ', ' so ', ' yet ', ' with ', ' to ']
    for conj in conjunctions:
        pos = summary.rfind(conj, cut_search_start, max_length)
        if pos > 0:
            best_end = pos
            break
    
    # If we found a conjunction, cut there
    if best_end > 0:
        return summary[:best_end].strip()
    
    # Last resort: Find the nearest word boundary
    for i in range(max_length, cut_search_start, -1):
        if i < len(summary) and summary[i] == ' ':
            best_end = i
            break
    
    # If we found a word boundary, use it
    if best_end > 0:
        return summary[:best_end].strip()
    
    # Absolute fallback: just cut at max_length (should rarely happen with all our checks)
    return summary[:max_length].strip()

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
                
                # Create a focused prompt that emphasizes brevity and specificity
                context = f"The page is titled '{link_title}'. " if link_title else ""
                prompt = (
                    f"{context}Provide a single, concise sentence summarizing the main purpose or "
                    f"specific offering of the following web page content. Focus on describing what makes "
                    f"this page unique or what specific service/product/information it offers. "
                    f"Do not include ellipses. Make it informative but brief:\n\n{page_content}"
                )
                
                # Call OpenAI API with refined settings for better summaries
                response = openai_client.chat.completions.create(
                    model="gpt-3.5-turbo",
                    messages=[
                        {"role": "system", "content": "You are a helpful assistant that summarizes web page content in exactly one concise, informative sentence."},
                        {"role": "user", "content": prompt}
                    ],
                    max_tokens=100,
                    temperature=0.3,  # Lower temperature for more focused responses
                    presence_penalty=-0.1  # Slight negative value to avoid redundancy
                )
                
                # Extract summary from response
                summary = response.choices[0].message.content.strip()
                
                # Clean and properly truncate the summary
                summary = clean_summary(summary, 150)
                
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
            return clean_summary(description, 150)
    
    # Try page title
    if soup.title and soup.title.string:
        title = soup.title.string.strip()
        if title:
            return clean_summary(title, 150)
    
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
        return clean_summary(content, 150)
    
    # Use link title if available
    if link_title:
        return f"{error_prefix}Page about {link_title}"
    
    # Last resort
    return f"{error_prefix}Page at {page_url}"

def format_llms_text(website_url, site_description, summarized_links):
    """
    Format the llms.txt content according to the competitor's format.
    Ensures proper sorting and formatting of links.
    
    Args:
        website_url (str): The main website URL
        site_description (str): The site description
        summarized_links (list): List of dictionaries with 'summary', 'url', and 'title' keys
        
    Returns:
        str: Formatted llms.txt content
    """
    # Get domain name from URL
    parsed_url = urlparse(website_url)
    domain_name = parsed_url.netloc
    
    # Format the header
    llms_text = f"# {domain_name} llms.txt\n\n"
    
    # Add site description
    llms_text += f"> {site_description}\n\n"
    
    # Sort the summarized links alphabetically by link title, ensuring case-insensitive sort
    # This ensures consistent ordering regardless of title capitalization
    sorted_links = sorted(summarized_links, key=lambda x: x["title"].lower())
    
    # Add each link in the format: - [Link Title](URL): Summary
    for link in sorted_links:
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
    
    # List of generic link texts
    generic_texts = [
        'read more',
        'learn more',
        'click here',
        'here',
        'view details',
        'details',
        'discover',
        'explore',
        'find out more',
        'more',
        'continue',
        'continue reading',
        'view',
        'view now',
        'see more',
        'see all',
        'get started',
        'sign up',
        'register',
        'login',
        'sign in',
        'home',
        'homepage',
        'back',
        'next',
        'previous',
        'submit',
        'send',
        'go',
        'go to',
        'contact',
        'contact us',
        'about',
        'about us',
        'services',
        'products',
        'blog',
        'article',
        'shop',
        'store',
    ]
    
    # Check if text is in the generic list
    for generic in generic_texts:
        if text == generic:
            return True
            
    # Check if text is too short (and not in the whitelist)
    if len(text) < 15:
        # Whitelist of short but specific terms
        short_whitelist = ['pricing', 'features', 'download', 'subscribe']
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
        
        # Identify common pages and make them more descriptive
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
    Enhanced to better prioritize content block titles, especially for Attrock-style sites.
    
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
    # Match common content block classes with flexible regex
    container = a_tag.find_parent(class_=lambda c: c and any(
        re.search(r'(post|card|entry|tool|service|feature|product|article|widget|item)', c) 
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
    Extract internal links from the parsed HTML.
    
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
    
    return internal_links

def fetch_page_and_extract_full_content(page_url, link_title=None):
    """
    Fetches a web page and extracts its main content without LLM summarization.
    This version aims to get as much relevant text as possible.
    
    Args:
        page_url (str): The URL of the page to fetch
        link_title (str, optional): The title of the link (for context in error messages)
        
    Returns:
        str: The extracted and cleaned main content of the page, or an error message.
    """
    try:
        if not check_robots_txt(page_url):
            return f"Respecting robots.txt: Not allowed to access {page_url}"
        
        logger.info(f"Fetching full content for page: {page_url}")
        response = requests.get(page_url, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Remove likely irrelevant elements
        for element in soup.find_all(['nav', 'footer', 'aside', 'style', 'script', 'noscript', 'header', 'form', 'img', 'svg', 'iframe']):
            element.decompose()
        
        # Prioritize main content areas for extraction
        full_page_content = ""
        content_selectors = [
            'main', 'article', 'div[role="main"]', '.main-content', '.content', '.article',
            '.post-content', '.entry-content', '.article-content', '.blog-content',
            'section', 'div[class*="body"]', 'div[class*="page-body"]', 'div[class*="text"]'  # Added more general selectors
        ]
        
        for selector in content_selectors:
            elements = soup.select(selector)
            for element in elements:
                text = ' '.join(element.get_text(strip=True, separator=' ').split())
                if text and len(text) > 50:  # Ensure it's substantial text
                    full_page_content += text + "\n\n"  # Add double newline for separation
        
        # Fallback if primary selectors don't yield enough content
        if not full_page_content and soup.body:
            full_page_content = ' '.join(soup.body.get_text(strip=True, separator=' ').split())
        
        full_page_content = clean_text(full_page_content)  # Apply existing cleaning function
        
        return full_page_content if full_page_content else f"No substantial content extracted from {page_url}"
        
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

def format_llms_full_text(website_url, site_description, full_content_sections):
    """
    Format the llms-full.txt content.
    
    Args:
        website_url (str): The main website URL
        site_description (str): The site description
        full_content_sections (list): List of dictionaries with 'title', 'url', and 'content' keys
        
    Returns:
        str: Formatted llms-full.txt content
    """
    parsed_url = urlparse(website_url)
    domain_name = parsed_url.netloc
    
    llms_full_text = f"# {domain_name} llms-full.txt\n\n"
    llms_full_text += f"Website Description: {site_description}\n\n"
    llms_full_text += "--- Start Full Website Content ---\n\n"
    
    # Sort by title for consistent output
    sorted_sections = sorted(full_content_sections, key=lambda x: x.get("title", "").lower())
    
    for section in sorted_sections:
        title = section.get("title", "No Title Available")
        url = section.get("url", "No URL Available")
        content = section.get("content", "No content extracted for this page.")
        
        llms_full_text += f"## Page Title: {title}\n"
        llms_full_text += f"URL: {url}\n\n"
        llms_full_text += f"{content}\n\n"
        llms_full_text += "---\n\n"  # Use a clear separator between pages
        
    llms_full_text += "--- End Full Website Content ---\n"
    
    return llms_full_text

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

@app.route('/generate_llm_text', methods=['POST'])
def generate_llm_text():
    try:
        data = request.get_json()
        website_url = data.get('websiteUrl')
        output_type = data.get('outputType', 'llms_txt')  # Get the new outputType, default to 'llms_txt'

        if not website_url:
            return jsonify({"error": "Website URL is required"}), 400

        if not validators.url(website_url):
            return jsonify({"error": "Invalid URL format"}), 400

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

        if output_type == 'llms_txt':
            logger.info("Generating LLM Text (summarized)")
            summarized_links = []
            with concurrent.futures.ThreadPoolExecutor(max_workers=CONCURRENT_WORKERS) as executor:
                future_to_link = {executor.submit(get_page_summary, link["url"], link["description"]): link for link in valid_links}
                for i, future in enumerate(concurrent.futures.as_completed(future_to_link)):
                    link = future_to_link[future]
                    try:
                        summary = future.result()
                        summarized_links.append({
                            "summary": summary,
                            "url": link["url"],
                            "title": link["description"]
                        })
                    except Exception as exc:
                        logger.error(f"Error processing link {link['url']}: {str(exc)}")
                        summarized_links.append({
                            "summary": f"Error processing: {link['url']}",
                            "url": link["url"],
                            "title": link["description"]
                        })
            
            logger.info("Formatting llms.txt content")
            llms_text = format_llms_text(website_url, site_description, summarized_links)
            
            logger.info("Successfully generated llms.txt content")
            return jsonify({
                "llms_text": llms_text,
                "site_description": site_description,
                "summarized_links": summarized_links
            })

        elif output_type == 'llms_full_txt':
            logger.info("Generating LLM Full Text (full content)")
            full_content_sections = []
            with concurrent.futures.ThreadPoolExecutor(max_workers=CONCURRENT_WORKERS) as executor:
                # Use partial to pass fetch_page_and_extract_full_content for each link
                fetch_and_extract_func = partial(fetch_page_and_extract_full_content)  # This new function must be defined below
                future_to_link = {executor.submit(fetch_and_extract_func, link["url"], link["description"]): link for link in valid_links}

                for i, future in enumerate(concurrent.futures.as_completed(future_to_link)):
                    link = future_to_link[future]
                    try:
                        page_full_content = future.result()
                        full_content_sections.append({
                            "title": link["description"],
                            "url": link["url"],
                            "content": page_full_content
                        })
                    except Exception as exc:
                        logger.error(f"Error processing full content for link {link['url']}: {str(exc)}")
                        full_content_sections.append({
                            "title": link["description"],
                            "url": link["url"],
                            "content": f"Error fetching or extracting content for {link['url']}: {str(exc)}"
                        })
            
            logger.info("Formatting llms-full.txt content")
            llms_full_text_output = format_llms_full_text(website_url, site_description, full_content_sections)  # This new function must be defined below
            
            logger.info("Successfully generated llms-full.txt content")
            return jsonify({
                "llms_full_text": llms_full_text_output,
                "site_description": site_description,
                "full_content_sections": full_content_sections
            })

        else:
            logger.warning(f"Invalid outputType received: {output_type}")
            return jsonify({"error": "Invalid outputType specified"}), 400
        
    except requests.exceptions.RequestException as e:
        error_message = f"Failed to fetch website: {str(e)}"
        logger.error(f"Request error: {error_message}")
        return jsonify({"error": error_message}), 500
    except Exception as e:
        error_message = f"Error processing website content: {str(e)}"
        logger.error(f"Processing error: {error_message}")
        return jsonify({"error": error_message}), 500

if __name__ == '__main__':
    logger.info("Starting LLM Text Generator application")
    app.run(debug=True) 