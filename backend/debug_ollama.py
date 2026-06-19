import ollama

tools = [{
    "type": "function",
    "function": {
        "name": "list_dir",
        "description": "Elenca i file in una cartella",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string"}
            },
            "required": ["path"]
        }
    }
}]

messages = [{"role": "user", "content": "quali file ci sono?"}]

print("Invocazione 1...")
response = ollama.chat(model="qwen3:8b", messages=messages, tools=tools)
msg = response.message if hasattr(response, 'message') else response.get('message')

tc = msg.tool_calls if hasattr(msg, 'tool_calls') else msg.get('tool_calls')
print("Tool calls ricevuti:", tc)

if hasattr(msg, 'model_dump'):
    messages.append(msg.model_dump())
else:
    messages.append(dict(msg))

messages.append({
    "role": "tool",
    "content": "frontend\nbackend\nREADME.md",
})

print("Invocazione 2...")
response2 = ollama.chat(model="qwen3:8b", messages=messages, tools=tools)
msg2 = response2.message if hasattr(response2, 'message') else response2.get('message')
print("Contenuto 2:", msg2.content if hasattr(msg2, 'content') else msg2.get('content'))
tc2 = msg2.tool_calls if hasattr(msg2, 'tool_calls') else msg2.get('tool_calls')
print("Tool calls 2:", tc2)
