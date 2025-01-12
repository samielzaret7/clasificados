import streamlit as st
import pandas as pd
import plotly.express as px

# Load and prepare your dataframe here
df = pd.read_csv('/Users/zenmaster/Programming/clasificados/classifieds_data_v3.csv')  # Load your cleaned dataframe

# Ensure price is numeric
df['Price'] = df['Price'].replace('[\$,]', '', regex=True).astype(float)

# Group by County and calculate the number of listings and average price
county_summary = df.groupby('region').agg(
    properties_sold=('region', 'size'),
    average_price=('Price', 'mean')
).reset_index()

# Title of the dashboard
st.title("Real Estate Dashboard")

# Display the dataframe summary
st.subheader("Properties Sold by County")
st.write(county_summary)

# Pie chart: Distribution of Property Types
st.subheader("Distribution of Property Types")
property_type_counts = df['Type'].value_counts()
fig_pie = px.pie(df, names='Type', title='Distribution of Property Types')
st.plotly_chart(fig_pie)

# Box plot: Prices by Property Type
st.subheader("Box Plot: Prices by Property Type")
fig_box = px.box(df, x='Type', y='Price', title='Box Plot of Prices by Property Type')
st.plotly_chart(fig_box)

# Heatmap: Prices by Region
st.subheader("Heatmap of Prices by Region")
pivot_table = df.pivot_table(index='region', values='Price', aggfunc='mean').reset_index()
fig_heatmap = px.density_heatmap(pivot_table, x='region', y='Price', title='Heatmap of Average Prices by Region')
st.plotly_chart(fig_heatmap)

# Scatter plot: Bedrooms vs Price
st.subheader("Scatter Plot: Bedrooms vs Price")
fig_scatter_bedrooms = px.scatter(df, x='Bedrooms', y='Price', title='Scatter Plot of Bedrooms vs Price')
st.plotly_chart(fig_scatter_bedrooms)

# Scatter plot: Property Type vs Price
st.subheader("Scatter Plot: Property Type vs Price")
fig_scatter_property_type = px.strip(df, x='Type', y='Price', title='Scatter Plot of Property Type vs Price')
st.plotly_chart(fig_scatter_property_type)


#add median income by county
# create a county profile (average price, average property type, etc.)
