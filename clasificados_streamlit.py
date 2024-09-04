import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
import plotly.express as px

# Load the CSS file
def load_css(file_name):
    with open(file_name) as f:
        st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)

# Load and apply the CSS
load_css("style.css")

# Streamlit app title
st.markdown('<div class="header"><h1>Real Estate Dashboard</h1></div>', unsafe_allow_html=True)

# Example content with custom styling
st.markdown('<div class="chart">This is where your chart will be displayed.</div>', unsafe_allow_html=True)

# Load and prepare your dataframe here
df = pd.read_csv('/Users/natalielewis/Desktop/p/clasificados/clasificados_sample.csv')  # Load your cleaned dataframe

# Ensure price is numeric
df['Price'] = df['Price'].replace('[\$,]', '', regex=True).astype(float)

# Group by County and calculate the number of listings and average price
county_summary = df.groupby('City').agg(
    properties_listed=('City', 'size'),
    average_price=('Price', 'mean')
).reset_index()

# Title of the dashboard
st.title("Real Estate Dashboard")

# Display the dataframe summary
st.subheader("Listed Properties by County") 
st.write(county_summary)

#Pyplot Bar chart: properties listed per county
county_summary_sorted = county_summary.sort_values(by='properties_listed', ascending=True)
custom_colors = ['#add057']
fig = px.bar(
    county_summary_sorted,
    x='City',
    y='properties_listed',
    title='Number of Properties Listed in Each County',
    labels={'City': 'County', 'properties_listed': 'Number of Properties Listed'},
    color='City',
    color_discrete_sequence=custom_colors
)
st.plotly_chart(fig)


# Bar chart: Average price per county
county_summary_sorted_price = county_summary.sort_values(by='average_price', ascending=False)
fig2 = px.bar(
    county_summary_sorted_price,
    x='City',
    y='average_price',
    title='Average Property Price in Each County',
    labels={'City': 'County', 'average_price': 'Average Price ($)'},
    color='City',
    color_discrete_sequence=custom_colors
)

st.plotly_chart(fig2)

type_counts = df['Type'].value_counts().reset_index()
type_counts.columns = ['Type','Count']
type_per_county = df.groupby(['City' , 'Type']).size().reset_index(name='Count')

pie_fig = px.pie(
    type_counts,
    names = 'Type',
    values = 'Count',
     title = 'Distribution of Properties by Type',
     color_discrete_sequence=px.colors.qualitative.Pastel
)
st.plotly_chart(pie_fig)

#add057
#00bca3