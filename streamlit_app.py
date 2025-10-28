import streamlit as st
from data import districts, approved_labour_budget #,percent_of_utilization

option = st.selectbox(
    "Select state for details...",
    districts,
    placeholder="Select a saved email or enter a new one",
    accept_new_options=True,
)

st.write("Your selection:", option)

st.metric(label="Approved labour budget", value=approved_labour_budget[0], border=True)

# a, b, c = st.columns(3)
# d, e, f = st.columns(3)

# progress_text = "Percentage payments gererated within 15 days"
# my_bar = st.progress(0, text=progress_text)
# percent_complete = 0
# for percent_complete in range(percent_of_utilization[0]):
#     time.sleep(0.01)
#     my_bar.progress(percent_complete + 1, text=progress_text)
