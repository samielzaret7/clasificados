import streamlit as st
import pandas as pd
import plotly.express as px

# Load and prepare your dataframe here
df = pd.read_csv('/Users/natalielewis/Desktop/p/clasificados/classifieds_data_v3.csv')  # Load your cleaned dataframe

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
#st.subheader("Properties Sold by County")
#st.write(county_summary)

# Display average home price per region as cards with borders
st.subheader("Average Home Price per Region")
cols = st.columns(5)
for index, row in county_summary.iterrows():
    with cols[index % 5]:
        st.markdown(
            f"""
            <div style="border: 2px solid #4CAF50; padding: 10px; border-radius: 5px;">
                <h3 style="text-align: center;">{row['region']}</h3>
                <p style="text-align: center; font-size: 24px;">${int(row['average_price']):,}</p>
            </div>
            """,
            unsafe_allow_html=True
        )

# Create columns for better layout
col1, col2 = st.columns([1,1])

# Box plot: Prices by Property Type
with col1:
    st.subheader("Average Prices by Region")
    fig_bar = px.bar(county_summary, x='region', y='average_price') #title='Average Prices by Region')
    st.plotly_chart(fig_bar)

# Pie chart: Distribution of Property Types
with col2:
    st.subheader("Distribution of Property Types")
    property_type_counts = df['Type'].value_counts()
    fig_pie = px.pie(df, names='Type') #title='Distribution of Property Types')
    st.plotly_chart(fig_pie)


col3, col4 = st.columns([1,1])

# Scatter plot: Property Type vs Price
with col3:
    st.subheader("Property Type vs Price")
    fig_scatter_property_type = px.strip(df, x='Type', y='Price') #title='Scatter Plot of Property Type vs Price')
    st.plotly_chart(fig_scatter_property_type)
    
# Heatmap: Prices by Region
with col4:
    st.subheader("Prices by Property Type")
    fig_box = px.box(df, x='Type', y='Price')#, title='Box Plot of Prices by Property Type')
    st.plotly_chart(fig_box)

# Scatter plot: Bedrooms vs Price
st.subheader("Bedrooms vs Price")
fig_scatter_bedrooms = px.scatter(df, x='Bedrooms', y='Price', title='Scatter Plot of Bedrooms vs Price')
st.plotly_chart(fig_scatter_bedrooms)

