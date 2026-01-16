from dataclasses import is_dataclass

from dacite import Config


def dict_to_data_class[T](
    data_class: T,
    data: dict,
    config: Config = Config(),
) -> T:
    """
    Convert a dictionary to a dataclass instance.

    :param data_class: The dataclass type.
    :param data: The dictionary to convert.
    :param config: The configuration for the conversion.
    :return: An instance of the dataclass.
    """
    if not is_dataclass(data_class):
        raise TypeError(f"{data_class} is not a dataclass")

