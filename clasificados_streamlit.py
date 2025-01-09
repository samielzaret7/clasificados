import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt

# Load and prepare your dataframe here
df = pd.read_csv('/Users/zenmaster/Programming/clasificados/classifieds_data.csv')  # Load your cleaned dataframe

# Ensure price is numeric
df['Price'] = df['Price'].replace('[\$,]', '', regex=True).astype(float)

# Group by County and calculate the number of listings and average price
county_summary = df.groupby('City').agg(
    properties_sold=('City', 'size'),
    average_price=('Price', 'mean')
).reset_index()

# Title of the dashboard
st.title("Real Estate Dashboard")

# Display the dataframe summary
st.subheader("Properties Sold by County")
st.write(county_summary)

# Bar chart: Properties sold per county
st.subheader("Number of Properties Sold in Each County")
plt.figure(figsize=(10, 6))
plt.bar(county_summary['City'], county_summary['properties_sold'], color='skyblue')
plt.xlabel('County')
plt.ylabel('Number of Properties Sold')
plt.xticks(rotation=45, ha='right')
st.pyplot(plt)

# Bar chart: Average price per county
st.subheader("Average Property Price in Each County")
plt.figure(figsize=(10, 6))
plt.bar(county_summary['City'], county_summary['average_price'], color='lightgreen')
plt.xlabel('County')
plt.ylabel('Average Price ($)')
plt.xticks(rotation=45, ha='right')
st.pyplot(plt)
