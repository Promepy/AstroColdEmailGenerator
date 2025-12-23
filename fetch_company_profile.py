#!/usr/bin/env python3
"""
Fetch LinkedIn company profile using Apify actor `ipHw77V2NMJPy8sbS`.

Behavior:
- Reads API token from environment variable `APIFY_TOKEN`.
- Calls the actor with a LinkedIn company identifier.
- Saves the result as JSON file.
"""
import os
import sys
import json
import re
from apify_client import ApifyClient


def read_token():
    """Read Apify API token from environment variable."""
    token = os.getenv("APIFY_TOKEN")
    if token:
        return token.strip()
    
    # Fallback: Try reading from .env file
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if os.path.exists(env_path):
        with open(env_path, "r") as f:
            for line in f:
                if line.startswith("APIFY_TOKEN="):
                    return line.split("=", 1)[1].strip()
    
    return None


def sanitize_filename(name):
    """Convert name to a safe filename."""
    name = re.sub(r'[<>:"/\\|?*]', '', name)
    name = name.replace(' ', '_')
    name = name.strip('. ')
    return name if name else "Unknown_Company"


def validate_linkedin_company_url(url):
    """
    Validate if the URL is a valid LinkedIn company URL.
    
    Args:
        url: String URL to validate
        
    Returns:
        Boolean indicating if URL is valid
    """
    if not url:
        return False
    
    # Pattern for LinkedIn company URLs
    # Matches: https://www.linkedin.com/company/name/ or https://linkedin.com/company/name
    pattern = r'^https?://(www\.)?linkedin\.com/company/[\w\-]+/?$'
    return bool(re.match(pattern, url.strip()))


def extract_company_identifier(linkedin_url):
    """Extract company identifier from LinkedIn company URL."""
    match = re.search(r'/company/([^/]+)', linkedin_url)
    if match:
        return match.group(1)
    return "unknown"


def fetch_linkedin_company(linkedin_url, output_path=None, filename=None):
    """
    Fetch a LinkedIn company profile and save it as JSON.
    
    Args:
        linkedin_url: The LinkedIn company URL (e.g., https://www.linkedin.com/company/google/)
        output_path: Directory path to save the file (default: current directory)
        filename: Custom filename (default: auto-generated from company name)
        
    Returns:
        Tuple of (success: bool, filepath: str or None, company_data: dict or None)
    """
    # Validate URL first
    if not validate_linkedin_company_url(linkedin_url):
        print("[ERROR] Invalid LinkedIn company URL: {}".format(linkedin_url))
        print("   Expected format: https://www.linkedin.com/company/company-name/")
        return (False, None, None)
    
    token = read_token()
    if not token:
        print("[ERROR] Apify API token not found. Set APIFY_TOKEN environment variable.")
        return (False, None, None)

    try:
        client = ApifyClient(token)
        
        # Extract company identifier from URL
        company_identifier = extract_company_identifier(linkedin_url)
        
        run_input = {
            "identifier": [company_identifier]
        }

        print("[INFO] Fetching company profile for: {}".format(linkedin_url))
        print("[INFO] Company identifier: {}".format(company_identifier))
        
        # Use the company scraper actor
        run = client.actor("ipHw77V2NMJPy8sbS").call(run_input=run_input)

        dataset_id = run.get("defaultDatasetId")
        if not dataset_id:
            print("[ERROR] No dataset produced by the run.")
            return (False, None, None)

        # Fetch items from dataset
        items = list(client.dataset(dataset_id).iterate_items())
        
        if not items:
            print("[ERROR] No data returned from the actor.")
            return (False, None, None)
        
        # Get the first (and should be only) item
        company_data = items[0]
        
        # Determine filename
        if filename:
            final_filename = filename
        else:
            # Try to get name from company data
            company_name = None
            if "basic_info" in company_data:
                company_name = company_data.get("basic_info", {}).get("name")
            if not company_name:
                company_name = company_identifier
            safe_name = sanitize_filename(company_name)
            final_filename = "{}_company.json".format(safe_name)
        
        # Determine full path
        if output_path:
            os.makedirs(output_path, exist_ok=True)
            full_path = os.path.join(output_path, final_filename)
        else:
            full_path = final_filename
        
        # Save to JSON file
        with open(full_path, 'w', encoding='utf-8') as f:
            json.dump(company_data, f, indent=2, ensure_ascii=False)
        
        print("[OK] Company profile saved to: {}".format(full_path))
        return (True, full_path, company_data)
        
    except Exception as e:
        print("[ERROR] Failed to fetch company profile: {}".format(str(e)))
        # Try to save error response if available
        if output_path and filename:
            try:
                error_path = os.path.join(output_path, filename)
                with open(error_path, 'w', encoding='utf-8') as f:
                    json.dump({"error": str(e)}, f, indent=2)
            except:
                pass
        return (False, None, None)


def validate_company_data(company_data):
    """
    Validate that company data is complete and usable.
    
    Args:
        company_data: Dictionary or list containing company data
        
    Returns:
        Tuple of (is_valid: bool, error_message: str or None)
    """
    if not company_data:
        return (False, "No company data received")
    
    # Handle array format
    if isinstance(company_data, list):
        if len(company_data) == 0:
            return (False, "No company data in array")
        company_data = company_data[0]
    
    # Check for error field in response (Apify free plan limitation)
    if "error" in company_data:
        error_msg = company_data.get("error", "Unknown error")
        if "free Apify plan" in error_msg:
            return (False, "Unable to fetch company. This feature requires a paid Apify subscription.")
        return (False, error_msg)
    
    # Check for essential fields
    company_name = None
    description = None
    
    # Check nested structure (basic_info)
    if "basic_info" in company_data:
        basic_info = company_data.get("basic_info", {})
        company_name = basic_info.get("name")
        description = basic_info.get("description")
    
    if not company_name:
        return (False, "Company data is incomplete. Missing company name.")
    
    # Check if data appears to be empty or minimal
    if len(str(company_data)) < 100:
        return (False, "Company data appears incomplete.")
    
    return (True, None)


def main():
    """Example usage."""
    linkedin_url = "https://www.linkedin.com/company/google/"
    success, filepath, data = fetch_linkedin_company(linkedin_url)
    
    if success and data:
        print("\nCompany Summary:")
        basic_info = data.get('basic_info', {})
        print("   Name: {}".format(basic_info.get('name', 'N/A')))
        print("   Industries: {}".format(basic_info.get('industries', 'N/A')))


if __name__ == "__main__":
    main()
