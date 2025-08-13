import re


def from_snake_case_to_camel_case(string: str) -> str:
    splitted = string.split("_")
    return splitted[0] + "".join(word.capitalize() for word in splitted[1:])


def dict_keys_to_camel_case(dictionary: dict) -> dict:
    new_dictionary = {}
    for key, value in dictionary.items():
        if isinstance(value, dict):
            new_dictionary[from_snake_case_to_camel_case(key)] = dict_keys_to_camel_case(value)
        else:
            new_dictionary[from_snake_case_to_camel_case(key)] = value

    return new_dictionary


def from_camel_case_to_snake_case(string: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", string).lower()


def dict_keys_to_snake_case(dictionary: dict) -> dict:
    new_dictionary = {}
    for key, value in dictionary.items():
        if isinstance(value, dict):
            new_dictionary[from_camel_case_to_snake_case(key)] = dict_keys_to_snake_case(value)
        else:
            new_dictionary[from_camel_case_to_snake_case(key)] = value

    return new_dictionary
