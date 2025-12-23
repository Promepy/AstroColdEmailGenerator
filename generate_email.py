#!/usr/bin/env python3
"""
Cold Email Generator using OpenAI GPT

Generates personalized cold emails based on LinkedIn profile/company data.
Uses prompt1.md for individual profiles and prompt2.md for companies.
"""
import os
import json
import sys
import time
import re
from typing import Dict, Any, Optional

from openai import OpenAI
from openai._exceptions import RateLimitError, APIStatusError


def read_api_key():
    """Read OpenAI API key from environment variable."""
    api_key = os.getenv("OPENAI_API_KEY")
    if api_key:
        return api_key.strip()
    
    # Fallback: Try reading from .env file
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if os.path.exists(env_path):
        with open(env_path, "r") as f:
            for line in f:
                if line.startswith("OPENAI_API_KEY="):
                    return line.split("=", 1)[1].strip()
    
    return None


def read_prompt_template(prompt_file):
    """Read an OpenAI prompt template from root directory."""
    prompt_path = os.path.join(os.path.dirname(__file__), prompt_file)
    try:
        with open(prompt_path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        print("[ERROR] Error reading prompt template {}: {}".format(prompt_file, e))
        return None


def with_backoff(fn, max_retries=6, base=2.0):
    """Retry function with exponential backoff for rate limits."""
    for i in range(max_retries):
        try:
            return fn()
        except RateLimitError as e:
            sleep = base ** i
            print("[WAIT] Rate limit, retry {}/{} in {:.1f}s".format(i+1, max_retries, sleep))
            time.sleep(sleep)
        except APIStatusError as e:
            status = getattr(e, "status_code", 0)
            if status in (429, 500, 502, 503, 504):
                sleep = base ** i
                print("[WAIT] API error {}, retry {}/{} in {:.1f}s".format(status, i+1, max_retries, sleep))
                time.sleep(sleep)
            else:
                raise
    raise RuntimeError("[ERROR] Exceeded retry attempts")


def extract_output_text(resp):
    """Extract text from Responses API response object."""
    try:
        txt = getattr(resp, "output_text", None)
        if txt:
            return txt
    except Exception:
        pass
    
    # Fallback: flatten outputs
    try:
        chunks = []
        for item in resp.output or []:
            if getattr(item, "content", None):
                for c in item.content:
                    t = getattr(c, "text", None)
                    if t:
                        chunks.append(t)
        if chunks:
            return "\n".join(chunks)
    except Exception:
        pass
    
    # Last resort: raw JSON
    try:
        return resp.model_dump_json()
    except Exception:
        return str(resp)


def extract_json_from_response(text):
    """Extract JSON from response text, handling markdown code blocks."""
    # Pattern to match JSON in code blocks
    code_block_pattern = r'```(?:json)?\s*([\s\S]*?)```'
    matches = re.findall(code_block_pattern, text)
    
    for match in matches:
        try:
            return json.loads(match.strip())
        except json.JSONDecodeError:
            continue
    
    # Try to parse the whole text as JSON
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    
    # Try to find JSON object in text
    try:
        start = text.find('{')
        end = text.rfind('}') + 1
        if start != -1 and end > start:
            return json.loads(text[start:end])
    except json.JSONDecodeError:
        pass
    
    return {"_parse_error": "Could not extract JSON", "_raw": text}


def generate_cold_email(client, model, prompt_text, profile_data, product_description, max_output_tokens=4000):
    """
    Call GPT to generate a cold email based on LinkedIn data.
    
    Args:
        client: OpenAI client
        model: Model name to use
        prompt_text: The prompt template
        profile_data: LinkedIn profile or company data
        product_description: One-liner product description
        max_output_tokens: Maximum tokens for output
        
    Returns:
        Dictionary with email content
    """
    user_payload = (
        "Product/Service being pitched:\n"
        "{}\n\n"
        "LinkedIn Data JSON:\n"
        "{}"
    ).format(product_description, json.dumps(profile_data, ensure_ascii=False, indent=2))
    
    # Combine instructions with user payload
    full_input = prompt_text + "\n\n" + user_payload
    
    def do_call():
        return client.responses.create(
            model=model,
            reasoning={"effort": "medium"},
            input=full_input,
            max_output_tokens=max_output_tokens,
        )
    
    print("   Input size: {:,} chars".format(len(full_input)))
    resp = with_backoff(do_call)
    txt = extract_output_text(resp)
    
    # Print usage stats
    if hasattr(resp, 'usage'):
        print("   Tokens: input={:,}, output={:,}".format(resp.usage.input_tokens, resp.usage.output_tokens))
    
    return extract_json_from_response(txt)


def run_email_generation(profile_json_path, product_description, profile_type="user", output_path=None):
    """
    Run the full email generation pipeline.
    
    Args:
        profile_json_path: Path to the profile/company JSON file
        product_description: One-liner product description
        profile_type: "user" or "company"
        output_path: Optional path to save the result
        
    Returns:
        The generation result as a dictionary, or None on failure
    """
    print("=" * 70)
    print("Cold Email Generator")
    print("=" * 70)
    
    # Configuration
    MODEL = "o4-mini"
    MAX_OUTPUT_TOKENS = 4000
    
    # Step 1: Read API key
    print("\n[STEP 1] Setup")
    print("-" * 70)
    api_key = read_api_key()
    if not api_key:
        print("[ERROR] OPENAI_API_KEY not found")
        return None
    print("[OK] API key loaded")
    
    client = OpenAI(api_key=api_key)
    
    # Step 2: Read appropriate prompt based on profile type
    print("\n[STEP 2] Loading Prompt")
    print("-" * 70)
    
    prompt_file = "prompt1.md" if profile_type == "user" else "prompt2.md"
    prompt_text = read_prompt_template(prompt_file)
    
    if not prompt_text:
        print("[ERROR] Failed to load {}".format(prompt_file))
        return None
    
    print("[OK] Loaded {} ({:,} chars)".format(prompt_file, len(prompt_text)))
    print("   Profile type: {}".format(profile_type))
    
    # Step 3: Load profile data
    print("\n[STEP 3] Loading Profile Data")
    print("-" * 70)
    
    try:
        with open(profile_json_path, "r", encoding="utf-8") as f:
            profile_data = json.load(f)
        print("[OK] Loaded profile from: {}".format(profile_json_path))
    except Exception as e:
        print("[ERROR] Error loading profile: {}".format(e))
        return None
    
    # Handle array format (extract first element)
    if isinstance(profile_data, list):
        if len(profile_data) == 0:
            print("[ERROR] Empty profile data array")
            return None
        profile_data = profile_data[0]
    
    # Display profile info
    if profile_type == "company":
        basic_info = profile_data.get("basic_info", {})
        name = basic_info.get("name", "Unknown Company")
        headline = ", ".join(basic_info.get("industries", [])) if basic_info.get("industries") else "N/A"
    else:
        if "basic_info" in profile_data:
            basic_info = profile_data.get("basic_info", {})
            name = basic_info.get("fullname", "Unknown")
            headline = basic_info.get("headline", "N/A")
        else:
            name = profile_data.get("fullName", "Unknown")
            headline = profile_data.get("headline", "N/A")
    
    print("   Name: {}".format(name))
    if len(headline) > 50:
        print("   Info: {}...".format(headline[:50]))
    else:
        print("   Info: {}".format(headline))
    print("   Product: {}".format(product_description[:50] + "..." if len(product_description) > 50 else product_description))
    
    # Step 4: Generate cold email
    print("\n[STEP 4] Generating Cold Email")
    print("-" * 70)
    print("[INFO] Generating email with {}...".format(MODEL))
    
    result = generate_cold_email(
        client, MODEL, prompt_text, profile_data, product_description, MAX_OUTPUT_TOKENS
    )
    
    # Check for parse errors
    if "_parse_error" in result:
        print("[WARN] JSON parse warning: {}".format(result['_parse_error']))
        # Try to extract email from raw text if available
        raw = result.get("_raw", "")
        if raw:
            # Simple extraction of email text
            result = {"email": raw}
    
    # Step 5: Save result if path provided
    if output_path:
        print("\n[STEP 5] Saving Results")
        print("-" * 70)
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print("[OK] Result saved to: {}".format(output_path))
    
    # Summary
    print("\n" + "=" * 70)
    print("[DONE] EMAIL GENERATED!")
    print("=" * 70)
    
    # Display generated email
    if "email" in result:
        print("\nGenerated Email:")
        print("-" * 40)
        print(result["email"])
        print("-" * 40)
    
    return result


def main():
    """Main function - can be called with command line args or imported."""
    if len(sys.argv) > 2:
        profile_path = sys.argv[1]
        product_description = sys.argv[2]
        profile_type = sys.argv[3] if len(sys.argv) > 3 else "user"
        output_path = sys.argv[4] if len(sys.argv) > 4 else None
    else:
        # Default test
        print("Usage: python generate_email.py <profile_json> <product_description> [user|company] [output_path]")
        return None
    
    result = run_email_generation(profile_path, product_description, profile_type, output_path)
    return result


if __name__ == "__main__":
    main()
