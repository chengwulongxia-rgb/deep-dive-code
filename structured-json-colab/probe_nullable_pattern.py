"""CPU-only regression probe for LM Format Enforcer 0.11.3 nullable string patterns."""
import importlib.metadata
import json
from lmformatenforcer import JsonSchemaParser


def probe(schema):
    parser=JsonSchemaParser(schema)
    for character in '"114':
        if character not in parser.get_allowed_characters():
            raise AssertionError('Prefix unexpectedly rejected: '+repr(character))
        parser=parser.add_character(character)
    return '-' in parser.get_allowed_characters()


if __name__=='__main__':
    pattern='^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
    result={'version':importlib.metadata.version('lm-format-enforcer'),'prefix':'"114',
            'string_schema_allows_premature_hyphen':probe({'type':'string','pattern':pattern}),
            'nullable_string_schema_allows_premature_hyphen':probe({'type':['string','null'],'pattern':pattern})}
    assert result['version']=='0.11.3'
    assert result['string_schema_allows_premature_hyphen'] is False
    assert result['nullable_string_schema_allows_premature_hyphen'] is True
    print(json.dumps(result,indent=2))
