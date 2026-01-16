import random

__url_alphabet = "ModuleSymbhasOwnPr-0123456789ABCDEFGHNRVfgctiUvz_KqYTJkLxpZXIjQW"

def nanoid(size: int = 21) -> str:
    id_chars = []
    for _ in range(size):
        # random.random() * 64 gives a float in [0,64)
        # int(...) floors it to 0–63
        idx = int(random.random() * len(__url_alphabet))
        id_chars.append(__url_alphabet[idx])
    return "".join(id_chars)

# Example usage:
if __name__ == "__main__":
    print(nanoid())       # e.g. "g3KpQ-5RA6fhY0NmtVz8N"
    print(nanoid(10))     # e.g. "Pr012345GH"
