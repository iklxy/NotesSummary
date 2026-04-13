"@Date:2026-04-13"
"@author:lixinyang"

import ollama

response = ollama.embed(
    model='bge-m3',
    input='The sky is blue because of Rayleigh scattering',
)
print(response.embeddings)