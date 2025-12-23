#!/usr/bin/env python3
"""
Flask Application for Cold Email Generator

Web interface for generating personalized cold emails from LinkedIn profiles and companies.
Supports both individual profiles (/in/username) and company pages (/company/name).
"""
import os
import sys
import json
import shutil
import re
from datetime import datetime

from flask import Flask, render_template, request, jsonify

# Import our modules
from fetch_user_profile import (
    fetch_linkedin_profile, 
    validate_linkedin_profile_url, 
    validate_profile_data
)
from fetch_company_profile import (
    fetch_linkedin_company,
    validate_linkedin_company_url,
    validate_company_data
)
from generate_email import run_email_generation

app = Flask(__name__)

# Configuration
WORK_DIR = os.path.join(os.path.dirname(__file__), "AllFiles")
os.makedirs(WORK_DIR, exist_ok=True)


def sanitize_filename(name):
    """Convert name to a safe filename."""
    if not name:
        return "Unknown"
    name = re.sub(r'[<>:"/\\|?*]', '', name)
    name = name.replace(' ', '_')
    name = name.strip('. ')
    return name if name else "Unknown"


def clear_work_directory():
    """Clear the working directory for fresh analysis."""
    if os.path.exists(WORK_DIR):
        for filename in os.listdir(WORK_DIR):
            file_path = os.path.join(WORK_DIR, filename)
            try:
                if os.path.isfile(file_path):
                    os.unlink(file_path)
                elif os.path.isdir(file_path):
                    shutil.rmtree(file_path)
            except Exception as e:
                print("Error deleting {}: {}".format(file_path, e))


def detect_url_type(url):
    """
    Detect if URL is a user profile or company page.
    
    Returns:
        'user', 'company', or None if invalid
    """
    if not url:
        return None
    
    url = url.strip()
    
    # Check for user profile pattern
    user_pattern = r'^https?://(www\.)?linkedin\.com/in/[\w\-]+/?$'
    if re.match(user_pattern, url):
        return 'user'
    
    # Check for company pattern
    company_pattern = r'^https?://(www\.)?linkedin\.com/company/[\w\-]+/?$'
    if re.match(company_pattern, url):
        return 'company'
    
    return None


# Clear on startup (but not on Flask reloader restarts)
is_reloader_restart = os.environ.get('WERKZEUG_RUN_MAIN') == 'true'
if not is_reloader_restart:
    print("[INIT] Initializing Cold Email Generator...")
    clear_work_directory()
    print("[INIT] Ready for email generation")


@app.route('/')
def index():
    """Render the main page."""
    return render_template('index.html')


@app.route('/api/validate-url', methods=['POST'])
def validate_url():
    """Validate a LinkedIn URL (user or company)."""
    data = request.get_json()
    url = data.get('url', '').strip()
    
    url_type = detect_url_type(url)
    
    if url_type == 'user':
        return jsonify({
            'valid': True,
            'type': 'user',
            'message': 'Valid LinkedIn profile URL'
        })
    elif url_type == 'company':
        return jsonify({
            'valid': True,
            'type': 'company',
            'message': 'Valid LinkedIn company URL'
        })
    else:
        return jsonify({
            'valid': False,
            'type': None,
            'message': 'Invalid URL. Expected format:\n• User: https://linkedin.com/in/username/\n• Company: https://linkedin.com/company/name/'
        })


@app.route('/api/generate', methods=['POST'])
def generate_email():
    """
    Full email generation pipeline:
    1. Detect URL type (user/company)
    2. Fetch LinkedIn data via Apify
    3. Generate cold email with GPT
    """
    data = request.get_json()
    url = data.get('url', '').strip()
    product_description = data.get('product_description', '').strip()
    
    # Validate URL
    url_type = detect_url_type(url)
    if not url_type:
        return jsonify({
            'success': False,
            'error': 'Invalid LinkedIn URL',
            'step': 'validation'
        }), 400
    
    # Validate product description
    if not product_description:
        return jsonify({
            'success': False,
            'error': 'Product description is required',
            'step': 'validation'
        }), 400
    
    if len(product_description) > 200:
        return jsonify({
            'success': False,
            'error': 'Product description must be 200 characters or less',
            'step': 'validation'
        }), 400
    
    try:
        # Clear previous files
        clear_work_directory()
        
        # Step 1: Fetch profile/company from LinkedIn via Apify
        print("\n[STEP 1] Fetching {} data from LinkedIn...".format(url_type))
        
        if url_type == 'user':
            success, profile_path, profile_data = fetch_linkedin_profile(
                url,
                output_path=WORK_DIR,
                filename="profile_data.json"
            )
            
            if not success:
                return jsonify({
                    'success': False,
                    'error': 'Failed to fetch LinkedIn profile. Please check the URL and try again.',
                    'step': 'fetch'
                }), 500
            
            # Validate profile data
            is_valid, validation_error = validate_profile_data(profile_data)
            
            if not is_valid:
                print("[ERROR] Profile data validation failed: {}".format(validation_error))
                return jsonify({
                    'success': False,
                    'error': validation_error,
                    'step': 'validation',
                    'details': 'Profile data could not be retrieved properly. Please ensure the profile is public.'
                }), 400
            
            # Extract basic info for response
            if isinstance(profile_data, list):
                profile_data = profile_data[0]
            
            if "basic_info" in profile_data:
                basic_info = profile_data.get("basic_info", {})
                full_name = basic_info.get("fullname", "Unknown")
                headline = basic_info.get("headline", "")
            else:
                full_name = profile_data.get("fullName", "Unknown")
                headline = profile_data.get("headline", "")
                
        else:  # company
            success, profile_path, profile_data = fetch_linkedin_company(
                url,
                output_path=WORK_DIR,
                filename="company_data.json"
            )
            
            if not success:
                return jsonify({
                    'success': False,
                    'error': 'Failed to fetch company data. Please check the URL and try again.',
                    'step': 'fetch'
                }), 500
            
            # Validate company data
            is_valid, validation_error = validate_company_data(profile_data)
            
            if not is_valid:
                print("[ERROR] Company data validation failed: {}".format(validation_error))
                return jsonify({
                    'success': False,
                    'error': validation_error,
                    'step': 'validation',
                    'details': 'Company data could not be retrieved properly.'
                }), 400
            
            # Extract basic info for response
            if isinstance(profile_data, list):
                profile_data = profile_data[0]
            
            basic_info = profile_data.get("basic_info", {})
            full_name = basic_info.get("name", "Unknown Company")
            industries = basic_info.get("industries", [])
            headline = ", ".join(industries) if industries else basic_info.get("description", "")[:100]
        
        print("   Fetched data for: {}".format(full_name))
        
        # Step 2: Generate cold email
        print("\n[STEP 2] Generating cold email...")
        output_path = os.path.join(WORK_DIR, "email_result.json")
        
        email_result = run_email_generation(
            profile_path, 
            product_description, 
            profile_type=url_type,
            output_path=output_path
        )
        
        if not email_result:
            return jsonify({
                'success': False,
                'error': 'Email generation failed. Please try again.',
                'step': 'generation'
            }), 500
        
        # Check for parse errors
        if "_parse_error" in email_result:
            print("   [WARN] Generation had parse issues but continuing...")
        
        # Extract email content
        email_content = email_result.get('email', '')
        
        if not email_content:
            return jsonify({
                'success': False,
                'error': 'No email was generated. Please try again.',
                'step': 'generation'
            }), 500
        
        print("   Email generated successfully!")
        
        return jsonify({
            'success': True,
            'message': 'Email generated successfully!',
            'profile': {
                'name': full_name,
                'headline': headline[:100] if headline else ''
            },
            'email': email_content,
            'url_type': url_type
        })
        
    except Exception as e:
        print("[ERROR] Error during generation: {}".format(str(e)))
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': 'An error occurred: {}'.format(str(e)),
            'step': 'unknown'
        }), 500


@app.route('/api/get-result')
def get_result():
    """Get the full generation result JSON."""
    result_path = os.path.join(WORK_DIR, "email_result.json")
    
    if not os.path.exists(result_path):
        return jsonify({
            'error': 'No result found. Please generate an email first.'
        }), 404
    
    try:
        with open(result_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return jsonify(data)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    print("")
    print("=" * 50)
    print("Cold Email Generator")
    print("=" * 50)
    print("Open http://localhost:5000 in your browser")
    print("=" * 50)
    print("")
    
    app.run(debug=False, port=5000, use_reloader=False)
