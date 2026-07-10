import requests
import time
import json

API_KEY = "bb_live_fSDDCS0aCiYII5SpOw5iTfkoISQ"
AGENT_ID = "ba9a3d56-9c5e-466a-a8ae-36f3b8a5b0d2"

BASE_URL = "https://api.browserbase.com/v1"

headers = {
    "Content-Type": "application/json",
    "X-BB-API-Key": API_KEY
}

task = input("Enter your research topic: ")

# -----------------------------
# CREATE RUN
# -----------------------------

payload = {
    "task": task,
    "agentId": AGENT_ID
}

print("\nCreating research run...\n")

response = requests.post(
    f"{BASE_URL}/agents/runs",
    headers=headers,
    json=payload
)

print("POST Status:", response.status_code)

if response.status_code != 201:
    print(response.text)
    exit()

run = response.json()

print("\nRun Created:\n")
print(json.dumps(run, indent=4))

run_id = run["runId"]

print(f"\nRun ID: {run_id}")

# -----------------------------
# POLL STATUS
# -----------------------------

while True:

    response = requests.get(
        f"{BASE_URL}/agents/runs/{run_id}",
        headers={
            "X-BB-API-Key": API_KEY
        }
    )

    print("GET Status:", response.status_code)

    if response.status_code != 200:
        print(response.text)
        break

    data = response.json()

    status = data["status"]

    print("Current Status:", status)

    if status == "COMPLETED":

        print("\n============================")
        print("RESEARCH COMPLETED")
        print("============================\n")

        # Print everything returned
        print(json.dumps(data, indent=4))

        print("\n============================")
        print("RESEARCH RESULT")
        print("============================\n")

        result = data.get("result")

        if result is not None:

            # If result is structured JSON
            if isinstance(result, dict):

                for key, value in result.items():

                    print(f"\n{'='*70}")
                    print(key.upper())
                    print(f"{'='*70}")

                    if isinstance(value, list):

                        for i, item in enumerate(value, 1):
                            print(f"{i}. {item}")

                    else:
                        print(value)

            else:
                print(result)

        else:
            print("No result returned.")
            print("Available Keys:")
            print(list(data.keys()))

        break

    elif status in ["FAILED", "STOPPED", "TIMED_OUT"]:

        print("\nRun Finished")
        print(json.dumps(data, indent=4))
        break

    time.sleep(10)