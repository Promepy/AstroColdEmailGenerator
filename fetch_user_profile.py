#!/usr/bin/env python3
"""
Fetch LinkedIn individual profile using Apify actor `VhxlqQXRwhW8H5hNV`.

Behavior:
- Reads API token from environment variable `APIFY_TOKEN`.
- Calls the actor with a LinkedIn profile URL (e.g., /in/username/).
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
    return name if name else "Unknown_Profile"


def validate_linkedin_profile_url(url):
    """
    Validate if the URL is a valid LinkedIn individual profile URL.
    
    Args:
        url: String URL to validate
        
    Returns:
        Boolean indicating if URL is valid
    """
    if not url:
        return False
    
    # Pattern for LinkedIn individual profile URLs
    # Matches: https://www.linkedin.com/in/username/ or https://linkedin.com/in/username
    pattern = r'^https?://(www\.)?linkedin\.com/in/[\w\-]+/?$'
    return bool(re.match(pattern, url.strip()))


def extract_username_from_url(linkedin_url):
    """Extract username from LinkedIn profile URL."""
    match = re.search(r'/in/([^/]+)', linkedin_url)
    if match:
        return match.group(1)
    return "unknown"


def fetch_linkedin_profile(linkedin_url, output_path=None, filename=None):
    """
    Fetch a LinkedIn individual profile and save it as JSON.
    
    Args:
        linkedin_url: The LinkedIn profile URL (e.g., https://www.linkedin.com/in/username/)
        output_path: Directory path to save the file (default: current directory)
        filename: Custom filename (default: auto-generated from profile name)
        
    Returns:
        Tuple of (success: bool, filepath: str or None, profile_data: dict or None)
    """
    # Validate URL first
    if not validate_linkedin_profile_url(linkedin_url):
        print("[ERROR] Invalid LinkedIn profile URL: {}".format(linkedin_url))
        print("   Expected format: https://www.linkedin.com/in/username/")
        return (False, None, None)
    
    token = read_token()
    if not token:
        print("[ERROR] Apify API token not found. Set APIFY_TOKEN environment variable.")
        return (False, None, None)

    try:
        client = ApifyClient(token)
        run_input = {
            "username": linkedin_url,
            "includeEmail": False
        }

        print("[INFO] Fetching profile for: {}".format(linkedin_url))
        run = client.actor("VhxlqQXRwhW8H5hNV").call(run_input=run_input)

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
        profile_data = items[0]
        
        # Determine filename
        if filename:
            final_filename = filename
        else:
            # Try to get name from profile data
            full_name = profile_data.get("fullName") or profile_data.get("firstName", "")
            if not full_name:
                full_name = extract_username_from_url(linkedin_url)
            safe_name = sanitize_filename(full_name)
            final_filename = "{}_profile.json".format(safe_name)
        
        # Determine full path
        if output_path:
            os.makedirs(output_path, exist_ok=True)
            full_path = os.path.join(output_path, final_filename)
        else:
            full_path = final_filename
        
        # Save to JSON file
        with open(full_path, 'w', encoding='utf-8') as f:
            json.dump(profile_data, f, indent=2, ensure_ascii=False)
        
        print("[OK] Profile saved to: {}".format(full_path))
        return (True, full_path, profile_data)
        
    except Exception as e:
        print("[ERROR] Failed to fetch profile: {}".format(str(e)))
        # Try to save error response if available
        if output_path and filename:
            try:
                error_path = os.path.join(output_path, filename)
                with open(error_path, 'w', encoding='utf-8') as f:
                    json.dump({"error": str(e)}, f, indent=2)
            except:
                pass
        return (False, None, None)


def validate_profile_data(profile_data):
    """
    Validate that profile data is complete and usable.
    Handles both flat structure and nested (array with basic_info) structure.
    
    Args:
        profile_data: Dictionary or list containing profile data
        
    Returns:
        Tuple of (is_valid: bool, error_message: str or None)
    """
    if not profile_data:
        return (False, "No profile data received")
    
    # Handle array format (new dataset structure)
    if isinstance(profile_data, list):
        if len(profile_data) == 0:
            return (False, "No profile data in array")
        profile_data = profile_data[0]
    
    # Check for error field in response (Apify free plan limitation)
    if "error" in profile_data:
        error_msg = profile_data.get("error", "Unknown error")
        if "free Apify plan" in error_msg:
            return (False, "Unable to fetch profile. This feature requires a paid Apify subscription. Please upgrade your Apify plan or use the Apify UI directly.")
        return (False, error_msg)
    
    # Check for essential fields - handle both flat and nested structures
    fullname = None
    headline = None
    
    # Check nested structure first (basic_info.fullname)
    if "basic_info" in profile_data:
        basic_info = profile_data.get("basic_info", {})
        fullname = basic_info.get("fullname") or basic_info.get("first_name")
        headline = basic_info.get("headline")
    else:
        # Check flat structure (fullName, headline)
        fullname = profile_data.get("fullName") or profile_data.get("firstName")
        headline = profile_data.get("headline")
    
    if not fullname:
        return (False, "Profile data is incomplete. Missing name information. The profile may be private or restricted.")
    
    if not headline:
        return (False, "Profile data is incomplete. Missing headline information. The profile may be private or restricted.")
    
    # Check if profile appears to be empty or minimal
    if len(str(profile_data)) < 100:  # Very small JSON suggests incomplete data
        return (False, "Profile data appears incomplete. The profile may be private or have limited information.")
    
    return (True, None)


def main():
    """Example usage."""
    linkedin_url = "https://www.linkedin.com/in/sree-swetha-kappagantula-b25355aa/"
    success, filepath, data = fetch_linkedin_profile(linkedin_url)
    
    if success and data:
        print("\nProfile Summary:")
        print("   Name: {}".format(data.get('fullName', 'N/A')))
        print("   Headline: {}".format(data.get('headline', 'N/A')))


if __name__ == "__main__":
    main()
