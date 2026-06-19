import ollama

tools = [{
    'type': 'function', 
    'function': {
        'name': 'list_dir', 
        'description': 'desc', 
        'parameters': {
            'type': 'object', 
            'properties': {'path': {'type': 'string'}}
        }
    }
}]

r = ollama.chat(
    model='gpt-oss:20b', 
    messages=[
        {'role': 'system', 'content': 'usa list_dir'}, 
        {'role': 'user', 'content': 'trova i bug'}
    ], 
    tools=tools
)

print('RAW CONTENT:', repr(r.message.content))
if hasattr(r.message, 'tool_calls'):
    print('TOOL CALLS:', getattr(r.message, 'tool_calls'))
else:
    print("NO TOOL CALLS")
