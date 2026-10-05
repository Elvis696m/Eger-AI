import requests

data = {
    "question": "What is animal science?",
    "answer": "Animal Science is the study of animals, including their nutrition, breeding, genetics, management, production and health."
}

response = requests.post(
    "http://127.0.0.1:5000/add",
    json=data
)

print(response.json())