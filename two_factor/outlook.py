import os
import re

from O365 import Account, FileSystemTokenBackend

__active_accounts: dict[str, Account] = {}
__FOLDER_NAME = os.getenv("O365_FOLDER_NAME", "AtoZ")

def authenticate(username: str) -> bool:
    """
    Authenticate the user with the given username.

    :param username: The username to authenticate.
    :return: True if authentication is successful, False otherwise.
    """
    __client_id = os.getenv("O365_CLIENT_ID")
    __client_secret = os.getenv("O365_CLIENT_SECRET")

    if username in __active_accounts:
        account = __active_accounts[username]
        if account.is_authenticated:
            return True
    else:

        account = Account((__client_id, __client_secret), username=username, token_backend=FileSystemTokenBackend(token_path="O365_tokens", token_filename=f"{username}.token"))
        __active_accounts[username] = account
        if not account.is_authenticated:
            # Authenticate the account
            if not account.authenticate(scopes=['basic', 'mailbox']):
                return False
            __active_accounts[username] = account
    return True

def get_2fa_code(username: str) -> str or None:
    """
    Get the 2FA code for the given username.

    :param username: The username to get the 2FA code for.
    :return: The 2FA code.
    """
    account = __active_accounts[username]
    if account is None:
        raise ValueError(f"Account for {username} not found")
    if not account.is_authenticated:
        raise ValueError(f"Account for {username} is not authenticated")
    # Get the 2FA code from the account
    mailbox = account.mailbox()
    folder = mailbox.get_folder(folder_name=__FOLDER_NAME)
    for message in folder.get_messages(limit=1):
        if "Amazon A to Z login verification code" in message.subject:
            return re.search(r'\d{6}', message.body).group()
    return None

