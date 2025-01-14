import streamlit as st
import pandas as pd
import plotly.express as px
from streamlit_elements import elements, dashboard

# Load and prepare your dataframe here
df = pd.read_csv('/Users/natalielewis/Desktop/p/clasificados/classifieds_data_v5.csv')  # Load your cleaned dataframe

# Ensure price is numeric
df['price'] = df['price'].replace('[\$,]', '', regex=True).astype(float)

# Group by County and calculate the number of listings and average price
county_summary = df.groupby('region').agg(
    properties_sold=('region', 'size'),
    average_price=('price', 'mean')
).reset_index()

# Title of the dashboard
st.title("Real Estate Dashboard")

# Define the layout for the dashboard items
layout = [
    dashboard.Item("average_price_cards", 0, 0, 6, 2),
    dashboard.Item("bar_chart", 0, 2, 6, 3),
    dashboard.Item("pie_chart", 6, 2, 6, 3),
    dashboard.Item("scatter_plot_type", 0, 5, 6, 3),
    dashboard.Item("box_plot", 6, 5, 6, 3),
]

# Create the draggable and resizable dashboard
with elements("dashboard"):
    with dashboard.Grid(layout):
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
                    unsafe_allow_html=True,
                    #key=f"average_price_card_{index}"
                )

        st.subheader("Average Prices by Region")
        fig_bar = px.bar(county_summary, x='region', y='average_price', title='Average Prices by Region')
        st.plotly_chart(fig_bar, key="bar_chart")

        st.subheader("Distribution of Property Types")
        property_type_counts = df['type'].value_counts()
        fig_pie = px.pie(df, names='type', title='Distribution of Property Types')
        st.plotly_chart(fig_pie, key="pie_chart")

        st.subheader("Property Type vs Price")
        fig_scatter_property_type = px.strip(df, x='type', y='price', title='Scatter Plot of Property Type vs Price')
        st.plotly_chart(fig_scatter_property_type, key="scatter_plot_type")

        st.subheader("Prices by Property Type")
        fig_box = px.box(df, x='type', y='price', title='Box Plot of Prices by Property Type')
        st.plotly_chart(fig_box, key="box_plot")

