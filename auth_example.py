"""
Example usage of the auth.py module.

This demonstrates how to use the refactored authentication system
with cookie persistence and reuse.
"""
from pathlib import Path
from auth import authenticate, CaptchaDetectedError
from config import TwoFAMethod
from two_factor.outlook import authenticate as outlook_auth, get_2fa_code


class OutlookTwoFAHandler:
    """Handler for Outlook-based two-factor authentication."""
    
    def __init__(self, outlook_email: str):
        self.outlook_email = outlook_email
        # Authenticate with Outlook when handler is created
        if not outlook_auth(outlook_email):
            raise ValueError(f"Failed to authenticate with Outlook: {outlook_email}")
    
    def pick_two_fa_option(self, options: list[tuple[str, object]]) -> tuple[str, object]:
        """
        Pick the matching 2FA option from available options.
        Since we've already filtered to the correct option in authenticate(),
        we just return the first one.
        """
        return options[0]
    
    def get_code(self) -> str:
        """Get the 2FA code from Outlook email."""
        code = get_2fa_code(self.outlook_email)
        if not code:
            raise ValueError("Failed to retrieve 2FA code from Outlook")
        return code


def example_authenticate_user():
    """Example of authenticating a user with cookie persistence."""
    
    # Configuration
    username = "your_username"
    password = "your_password"
    outlook_email = "your_email@outlook.com"
    cookie_path = Path("cookies") / f"{username}.pkl"
    
    # Create the 2FA handler
    two_fa_handler = OutlookTwoFAHandler(outlook_email)
    
    try:
        # Attempt authentication (will reuse cookies if available)
        auth_token = authenticate(
            username=username,
            password=password,
            two_fa_handler=two_fa_handler,
            cookie_path=cookie_path,
            two_fa_method=(TwoFAMethod.OUTLOOK, outlook_email),
            show_browser=False  # Set to True for debugging
        )
        
        print(f"✅ Authentication successful!")
        print(f"Auth token: {auth_token[:20]}..." if auth_token else "No token")
        return auth_token
        
    except CaptchaDetectedError as e:
        print(f"❌ CAPTCHA detected: {e}")
        print("Manual intervention required - try again later or use a different account")
        return None
        
    except Exception as e:
        print(f"❌ Authentication failed: {e}")
        return None


if __name__ == "__main__":
    example_authenticate_user()
