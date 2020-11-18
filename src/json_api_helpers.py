from marshmallow import Schema, fields, validate, ValidationError
import itertools

def format_errors(schema, errors, many):
    """Format validation errors as JSON Error objects."""
    if not errors:
        return {}
    if isinstance(errors, (list, tuple)):
        return {"errors": errors}

    formatted_errors = []
    if many:
        for index, i_errors in errors.items():
            formatted_errors.extend(_get_formatted_errors(schema, i_errors, index))
    else:
        formatted_errors.extend(_get_formatted_errors(schema, errors))

    return {"errors": formatted_errors}

def _get_formatted_errors(schema, errors, index=None):
    return itertools.chain(
        *(
            [
                format_error(schema, field_name, message, index=index)
                for message in field_errors
            ]
            for field_name, field_errors in itertools.chain(
                *(_process_nested_errors(schema, k, v) for k, v in errors.items())
            )
        )
    )

def _process_nested_errors(schema, name, data):
    if not isinstance(data, dict):
        return [(name, data)]

    return itertools.chain(
        *(_process_nested_errors(schema, f"{name}/{k}", v) for k, v in data.items())
    )

def format_error(schema, field_name, message, index=None):
    pointer = ["/data"]

    if index is not None:
        pointer.append(str(index))

    if field_name != "id":
        # JSONAPI identifier is a special field that exists above the attribute object.
        pointer.append("attributes")

    pointer.append(field_name)

    return {"detail": message, "source": {"pointer": "/".join(pointer)}}