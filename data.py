import json

try:
    with open('data.json', 'r') as f:
        data = json.load(f)
except FileNotFoundError:
    st.error("Error: 'data.json' not found. Please create the file.")
    st.stop()

districts=[]
approved_labour_budget=[]
# percent_of_utilization=[]

for i in data:
    districts.append(i["district_name"])
    approved_labour_budget.append(i["Approved_Labour_Budget"])
    # percent_of_utilization.append(int((i["percentage_payments_gererated_within_15_days"])))