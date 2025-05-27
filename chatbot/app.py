#LANGCHAIN_API_KEY="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"
#LANGCHAIN_PROJECT="GeneralChatbot"
# Import necessary libraries
import streamlit as st
import requests
from dotenv import load_dotenv
from datetime import datetime
from dateutil import parser
import spacy
import os
import random
import speech_recognition as sr  # Import the speech recognition library
from PIL import Image
from streamlit_lottie import st_lottie
import re
import uuid  # Import UUID for unique key generation
import mysql.connector
from mysql.connector import Error


from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
import io


# Load environment variables
load_dotenv()

#database connection

def create_mysql_connection():
    try:
        connection = mysql.connector.connect(
            host="localhost",
            user="root",  # Replace with your MySQL username
            password="root123",  # Replace with your MySQL password
            database="safarbot"
        )
        return connection
    except Error as e:
        st.error(f"Error connecting to MySQL: {e}")
        return None

# Load spaCy model for named entity recognition
nlp = spacy.load("en_core_web_sm")


def load_data_from_txt(filename):
    """Load data from text file containing Python dictionaries"""
    data = {}
    current_dict = None
    
    with open(filename, 'r', encoding='utf-8') as file:
        for line in file:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
                
            # Check if we're starting a new dictionary
            if line.endswith('= {'):
                current_dict = line.split('=')[0].strip()
                data[current_dict] = {}
                continue
                
            # Skip closing braces
            if line == '}' or line == '} ':
                current_dict = None
                continue
                
            # Parse dictionary items
            if current_dict and ':' in line:
                # Handle lines with multiple key-value pairs
                pairs = [pair.strip() for pair in line.split(',')]
                for pair in pairs:
                    if ':' in pair:
                        key, value = pair.split(':', 1)
                        key = key.strip().strip('"\'')
                        value = value.strip().strip('",\'')
                        data[current_dict][key] = value
    return data

# Load data from text file
data = load_data_from_txt('flightCardData.txt')

# Assign to variables
CITY_TO_IATA = data.get('CITY_TO_IATA', {})
AIRLINE_NAME_MAPPING = data.get('AIRLINE_NAME_MAPPING', {})
AIRPORT_TO_COUNTRY = data.get('AIRPORT_TO_COUNTRY', {})


# Define specific responses for flight booking queries
FLIGHT_BOOKING_RESPONSES = {
    "only_origin": "Please provide the destination city and departure date. (For ex. To Mumbai on March 2)",
    "only_destination": "Please provide the origin city and departure date. (For ex. From Mumbai on March 12 2025)",
    "only_date": "Please provide the origin and destination city. (For ex. From Mumbai to Delhi)",
    "origin_and_destination": "When would you like to travel? (For ex. On March 2 2025)",
    "origin_and_date": "Where would you like to travel to? (For ex. To Delhi)",
    "destination_and_date": "Where will you be flying from? (For ex. From Mumbai)",
    "all_details": "Great! Let me find flights for you.",
}

BOOKING_PROCESS_RESPONSE = """
Here's how to book flights through SafarBot in simple steps:


1️⃣ **Start a Booking Request**  
   - Say something like:  
     _"I want to book a flight from Delhi to Mumbai on March 15"_  
   - Or provide details separately when asked

2️⃣ **Provide Required Information**  
   - Origin city (where you're flying from)  
   - Destination city (where you're flying to)  
   - Travel date(s)  
   - Number of passengers  
   - Preferred airline (optional)

3️⃣ **Review Flight Options**  
   - I'll show available flights with:  
     - Airlines, timings & prices  
     - Different class options (Economy/Business/First)  
     - Duration and stops information

4️⃣ **Select Your Flight**  
   - Choose your preferred flight  
   - View special offers if available

5️⃣ **Enter Passenger Details**  
   - Provide names, contact info  
   - Passport details for international flights  
   - Select travel class

6️⃣ **Make Payment**  
   - Choose payment method  
   - Review final pricing  
   - Complete payment securely

7️⃣ **Get Confirmation**  
   - Receive booking reference  
   - Download e-ticket  
   - Get email confirmation

╰┈➤ **Tips for Easy Booking:**  
- Have your travel dates and passenger details ready  
- Check passport validity for international flights  

Would you like to start a booking now?
"""


# Function to generate random prices for different classes (per passenger)
def generate_random_prices(base_price_per_passenger):
    """Generate prices for different classes based on economy price for one passenger"""
    economy_price = base_price_per_passenger
    business_price = round(base_price_per_passenger * random.uniform(1.5, 2.5), 2)
    first_class_price = round(base_price_per_passenger * random.uniform(2.5, 4.0), 2)
    return {
        "Economy": economy_price,
        "Business": business_price,
        "First Class": first_class_price,
    }



def reset_context():
    """Reset all session state variables to their initial values"""
    st.session_state.clear()  # This clears ALL session state variables
    
    # Now reinitialize only the essential variables you need
    st.session_state.context = {}
    st.session_state.flight_params = {}
    st.session_state.search_triggered = False
    st.session_state.conversation = [{"role": "assistant", "content": "Hello! I'm your flight booking assistant. How can I help you today?"}]
    st.session_state.selected_flight_source = None
    st.session_state.current_page = "main"
    st.session_state.passengers = 1

# Function to parse user query and extract origin, destination, date, and airline
def parse_user_query(query, context):
    # Check for booking process questions first
    if any(phrase in query.lower() for phrase in ["how to book", "booking process", "booking steps", "how does this work"]):
        return "booking_process", None, None, None
    
    origin, destination, date, airline = context.get("origin"), context.get("destination"), context.get("date"), context.get("airline")
    doc = nlp(query)
    
    # Extract locations (cities)
    locations = [ent.text for ent in doc.ents if ent.label_ == "GPE"]
    
    # Determine if the user is specifying origin or destination
    if "from" in query.lower():
        origin = locations[0] if locations else None
    elif "to" in query.lower():
        destination = locations[0] if locations else None
    elif locations:
        # If no keyword, assume the first location is the destination
        destination = locations[0]
    
    # Extract date
    dates = [ent.text for ent in doc.ents if ent.label_ == "DATE"]
    if dates:
        try:
            parsed_date = parser.parse(dates[0], fuzzy=True)
            date = parsed_date.strftime("%Y-%m-%d")
        except ValueError:
            pass
    
    # Extract airline
    for airline_code, airline_name in AIRLINE_NAME_MAPPING.items():
        if airline_name.lower() in query.lower():
            airline = airline_code
            break
    
    return origin, destination, date, airline

# Function to determine the type of query
def determine_query_type(origin, destination, date):
    if origin and not destination and not date:
        return "only_origin"
    elif destination and not origin and not date:
        return "only_destination"
    elif date and not origin and not destination:
        return "only_date"
    elif origin and destination and not date:
        return "origin_and_destination"
    elif origin and date and not destination:
        return "origin_and_date"
    elif destination and date and not origin:
        return "destination_and_date"
    elif origin and destination and date:
        return "all_details"
    else:
        return None

# Function to generate access token for Amadeus API
def generate_access_token():
    response = requests.post(
        "https://test.api.amadeus.com/v1/security/oauth2/token",
        data={
            "grant_type": "client_credentials",
            "client_id": os.getenv("AMADEUS_API_KEY"),
            "client_secret": os.getenv("AMADEUS_API_SECRET"),
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"}
    )
    if response.status_code != 200:
        st.error(f"Failed to generate access token. Status Code: {response.status_code}, Response: {response.text}")
        return None
    return response.json().get("access_token")

# Function to fetch flight data from Amadeus API
def fetch_flight_data(origin, destination, date, token, airline=None, adults=1):
    params = {
        "originLocationCode": origin,
        "destinationLocationCode": destination,
        "departureDate": date,
        "adults": adults,
        "currencyCode": "INR",
        "max": 10,
    }
    headers = {"Authorization": f"Bearer {token}"}
    response = requests.get("https://test.api.amadeus.com/v2/shopping/flight-offers", headers=headers, params=params)
    if response.status_code != 200:
        st.error(f"Failed to fetch flight data. Status Code: {response.status_code}, Response: {response.text}")
        return []
    flights = response.json().get("data", [])
    return [f for f in flights if not airline or f["validatingAirlineCodes"][0] == airline]

def format_time(datetime_input):
    """Format time from either string or datetime object"""
    if isinstance(datetime_input, str):
        dt = datetime.strptime(datetime_input, "%Y-%m-%dT%H:%M:%S")
    else:
        dt = datetime_input
    return dt.strftime("%I:%M %p")  # Convert to 12-hour format

def format_date(datetime_input):
    """Format date from either string or datetime object"""
    if isinstance(datetime_input, str):
        dt = datetime.strptime(datetime_input, "%Y-%m-%dT%H:%M:%S")
    else:
        dt = datetime_input
    return dt.strftime("%d %b %Y")  # Convert to readable date format


def is_domestic_flight(origin_code, destination_code):
    """Check if flight is domestic (same country)"""
    origin_country = AIRPORT_TO_COUNTRY.get(origin_code, None)
    destination_country = AIRPORT_TO_COUNTRY.get(destination_code, None)
    
    if not origin_country or not destination_country:
        st.warning(f"Unknown airport code detected. Origin: {origin_code}, Destination: {destination_code}")
        return False  # Default to international if unknown airport
    
    return origin_country == destination_country

def passenger_details_page():
    st.title("✈️ Passenger Details")
    


    # Custom CSS for better styling
    st.markdown("""
    <style>
        .sidebar .stTabs [data-baseweb="tab"] {
            padding: 8px 12px;
            margin: 0 2px;
        }
        .sidebar .stTabs [aria-selected="true"] {
            background-color: #f0f2f6;
            border-radius: 6px;
            font-weight: 600;
        }
        .perk-item {
            margin-bottom: 10px;
            display: flex;
            align-items: flex-start;
        }
        .perk-icon {
            margin-right: 8px;
            color: #1e88e5;
            font-size: 16px;
        }
        .class-icon {
            border-radius: 50%;
            padding: 10px;
            background: #f5f5f5;
            margin-bottom: 15px;
            display: inline-block;
        }
    </style>
    """, unsafe_allow_html=True)
    
    # Class-specific information sidebar with custom icons
    with st.sidebar:
        st.subheader("✈️ Flight Class Benefits")
        
        # Create tabs for each class with specified icons
        tab1, tab2, tab3 = st.tabs(["Economy", "Business", "First Class"])
        
        with tab1:
            st.markdown("""
            <div style="text-align:center">
                <div class="class-icon">
                    <img src="https://cdn-icons-png.flaticon.com/512/11949/11949996.png" width="60">
                </div>
                <h3 style="margin-top:0">Economy Class</h3>
            </div>
            """, unsafe_allow_html=True)
            
            st.markdown("""
            <div class="perk-item"><span class="perk-icon">✓</span> Standard legroom seating</div>
            <div class="perk-item"><span class="perk-icon">✓</span> 1 checked bag (up to 23kg)</div>
            <div class="perk-item"><span class="perk-icon">✓</span> Complimentary meal/snack</div>
            <div class="perk-item"><span class="perk-icon">✓</span> Free seat selection (standard seats)</div>
            <div class="perk-item"><span class="perk-icon">✓</span> Entertainment on personal device</div>
            """, unsafe_allow_html=True)
            
            st.markdown("""
            <div style="margin-top:20px; padding:10px; background:#e3f2fd; border-radius:8px">
                <strong>Best for:</strong> Budget-conscious travelers
            </div>
            """, unsafe_allow_html=True)
        
        with tab2:
            st.markdown("""
            <div style="text-align:center">
                <div class="class-icon">
                    <img src="https://cdn-icons-png.flaticon.com/512/10577/10577823.png" width="60">
                </div>
                <h3 style="margin-top:0">Business Class</h3>
            </div>
            """, unsafe_allow_html=True)
            
            st.markdown("""
            <div class="perk-item"><span class="perk-icon">✓</span> Extra legroom seating</div>
            <div class="perk-item"><span class="perk-icon">✓</span> 2 checked bags (up to 32kg each)</div>
            <div class="perk-item"><span class="perk-icon">✓</span> Premium meals with drinks</div>
            <div class="perk-item"><span class="perk-icon">✓</span> Priority boarding</div>
            <div class="perk-item"><span class="perk-icon">✓</span> Lounge access (where available)</div>
            <div class="perk-item"><span class="perk-icon">✓</span> Lie-flat seats on long-haul</div>
            """, unsafe_allow_html=True)
            
            st.markdown("""
            <div style="margin-top:20px; padding:10px; background:#e8f5e9; border-radius:8px">
                <strong>Best for:</strong> Business travelers and comfort seekers
            </div>
            """, unsafe_allow_html=True)
        
        with tab3:
            st.markdown("""
            <div style="text-align:center">
                <div class="class-icon">
                    <img src="https://cdn-icons-png.flaticon.com/512/4319/4319571.png" width="60">
                </div>
                <h3 style="margin-top:0">First Class</h3>
            </div>
            """, unsafe_allow_html=True)
            
            st.markdown("""
            <div class="perk-item"><span class="perk-icon">✓</span> Private suites (where available)</div>
            <div class="perk-item"><span class="perk-icon">✓</span> 3 checked bags (up to 32kg each)</div>
            <div class="perk-item"><span class="perk-icon">✓</span> Gourmet dining with champagne</div>
            <div class="perk-item"><span class="perk-icon">✓</span> Dedicated check-in & security</div>
            <div class="perk-item"><span class="perk-icon">✓</span> Luxury lounge access</div>
            <div class="perk-item"><span class="perk-icon">✓</span> Full-flat bed with bedding</div>
            <div class="perk-item"><span class="perk-icon">✓</span> Premium amenity kit</div>
            """, unsafe_allow_html=True)
            
            st.markdown("""
            <div style="margin-top:20px; padding:10px; background:#f3e5f5; border-radius:8px">
                <strong>Best for:</strong> Ultimate luxury experience
            </div>
            """, unsafe_allow_html=True)
    
    # [Rest of your existing passenger details page code remains unchanged]
    # ...
    
    # Rest of your passenger details page code remains the same
    if all(key in st.session_state for key in ["selected_flight_index", "selected_offer", "selected_flight_source"]):
        flight_list = st.session_state.get(st.session_state.selected_flight_source, [])
        flight = flight_list[st.session_state.selected_flight_index]
        
        itinerary = flight["itineraries"][0]
        first_segment = itinerary["segments"][0]
        last_segment = itinerary["segments"][-1]
        airline_code = first_segment["carrierCode"]
        flight_code = f"{airline_code}{first_segment['number']}"
        
        # Get airport codes
        origin_code = first_segment['departure']['iataCode']
        destination_code = last_segment['arrival']['iataCode']
        domestic_flight = is_domestic_flight(origin_code, destination_code)
        
        # Display flight info (without class)
        st.subheader("Selected Flight")
        st.write(f"**Flight:** {AIRLINE_NAME_MAPPING.get(airline_code, airline_code)} {flight_code}")
        st.write(f"**Route:** {origin_code} → {destination_code} {'(Domestic)' if domestic_flight else '(International)'}")
        st.write(f"**Departure:** {format_date(first_segment['departure']['at'])} at {format_time(first_segment['departure']['at'])}")
        st.write(f"**Arrival:** {format_date(last_segment['arrival']['at'])} at {format_time(last_segment['arrival']['at'])}")
        
        st.markdown("---")
        # Display selected offer if available with cancel option
        if 'selected_offer' in st.session_state and st.session_state.selected_offer:
            offer = st.session_state.selected_offer
            st.subheader("Selected Offer")
            
            # Create columns for the offer card and cancel button
            col1, col2 = st.columns([4, 1])
            
            with col1:
                st.markdown(f"""
                <div style="
                    background-color: {offer['color']};
                    color: white;
                    padding: 15px;
                    border-radius: 8px;
                    box-shadow: 0px 4px 6px rgba(0, 0, 0, 0.1);
                    margin-bottom: 15px;
                ">
                    <h3 style="margin-top:0;">{offer['title']}</h3>
                </div>
                """, unsafe_allow_html=True)
            
            with col2:
                if st.button("✖", key="cancel_offer_button", help="Remove this offer from your booking"):
                    st.session_state.selected_offer = None
                    st.success("Offer has been removed")
                    st.subheader("No Offer Selected")
                    st.info("You're proceeding without any special offers")
                    st.rerun()
        else:    
            st.subheader("No Offer Selected")
            st.info("You're proceeding without any special offers")

        # Get passenger count from session state
        num_passengers = st.session_state.passengers
        
        # Initialize form submission state if not exists
        if "form_submitted" not in st.session_state:
            st.session_state.form_submitted = False

        with st.form("passenger_details_form", clear_on_submit=False):
            # Add single flight class selection at the top
            st.subheader("Flight Class for All Passengers")
            flight_class = st.selectbox(
                "Select Travel Class for All Passengers",
                ["Economy", "Business", "First Class"],
                index=["Economy", "Business", "First Class"].index(
                    st.session_state.get("passenger_details", {}).get("flight_class", "Economy")
                ),
                key="flight_class_all"
            )
            
            st.subheader(f"Passenger Details ({num_passengers} passenger{'s' if num_passengers > 1 else ''})")
            
            passengers = []
            # Get existing passenger details if they exist
            existing_details = st.session_state.get("passenger_details", {}).get("passengers", [])
            
            for i in range(1, num_passengers + 1):
                st.markdown(f"### Passenger {i}")
                
                # Get existing data for this passenger if available
                existing_data = existing_details[i-1] if i <= len(existing_details) else {}
                
                # Name fields with existing values
                cols = st.columns(2)
                with cols[0]:
                    first_name = st.text_input(
                        f"First Name (Passenger {i})", 
                        value=existing_data.get("first_name", ""),
                        key=f"first_name_{i}"
                    )
                with cols[1]:
                    last_name = st.text_input(
                        f"Last Name (Passenger {i})", 
                        value=existing_data.get("last_name", ""),
                        key=f"last_name_{i}"
                    )
                
                # Personal details with existing values
                cols = st.columns(2)
                with cols[0]:
                    gender = st.selectbox(
                        f"Gender (Passenger {i})", 
                        ["Male", "Female", "Other", "Prefer not to say"],
                        index=["Male", "Female", "Other", "Prefer not to say"].index(existing_data.get("gender", "Male")),
                        key=f"gender_{i}"
                    )
                with cols[1]:
                    dob = st.date_input(
                        f"Date of Birth (Passenger {i})", 
                        value=existing_data.get("dob", datetime.now().date()),
                        key=f"dob_{i}"
                    )
                
                

                # Conditional passport fields with existing values
                if not domestic_flight:
                    passport = st.text_input(
                        f"Passport Number (Passenger {i})", 
                        value=existing_data.get("passport", ""),
                        key=f"passport_{i}"
                    )
                    nationality = st.text_input(
                        f"Nationality (Passenger {i})", 
                        value=existing_data.get("nationality", ""),
                        key=f"nationality_{i}"
                    )
                else:
                    passport = "NOT_REQUIRED"
                    nationality = AIRPORT_TO_COUNTRY.get(origin_code, "")
                    st.write(f"Note: Passport not required for domestic flights within {nationality}")
                
                passengers.append({
                    "first_name": first_name,
                    "last_name": last_name,
                    "gender": gender,
                    "dob": dob,
                    "flight_class": flight_class,
                    "passport": passport,
                    "nationality": nationality
                })
            
            # Contact information with existing values
            existing_contact = st.session_state.get("passenger_details", {}).get("contact", {})
            st.markdown("### Contact Information")
            # Email validation
            email = st.text_input(
                "Email Address", 
                value=existing_contact.get("email", ""),
                key="email_input"
            )
            
            # Phone number validation
            phone = st.text_input(
                "Phone Number", 
                value=existing_contact.get("phone", ""),
                key="phone_input",
                max_chars=10  # Limit to 10 digits for Indian phone numbers
            )
            
            # Payment method with existing value
            existing_payment = st.session_state.get("passenger_details", {}).get("payment_method", "Credit Card")
            st.markdown("### Payment Method")
            payment_method = st.selectbox(
                "Select Payment Method", 
                ["Credit Card", "Debit Card", "Net Banking", "UPI", "PayPal"],
                index=["Credit Card", "Debit Card", "Net Banking", "UPI", "PayPal"].index(existing_payment)
            )
            
            # Terms and conditions - don't preserve this as it needs to be re-agreed
            agree = st.checkbox("I agree to the terms and conditions")
            
            if st.form_submit_button("Proceed to Payment"):
                # Validation logic
                validation_passed = True
                
                if not all([p['first_name'] and p['last_name'] for p in passengers]):
                    st.error("Please enter first and last names for all passengers")
                    validation_passed = False

                # Email validation
                email_pattern = re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$')
                if not email_pattern.match(email):
                    st.error("Please enter a valid email address (e.g., example@gmail.com)")
                    validation_passed = False
                
                # Phone number validation (for Indian numbers)
                if not phone or not phone.isdigit() or len(phone) != 10 or not phone.startswith(('6', '7', '8', '9')):
                    st.error("Please enter a valid 10-digit Indian phone number starting with 6,7,8, or 9")
                    validation_passed = False
                
                if validation_passed and email and phone and agree:
                    # Store ALL passenger details properly
                    st.session_state.passenger_details = {
                        "passengers": passengers,  # This now contains all passengers
                        "contact": {"email": email, "phone": phone},
                        "payment_method": payment_method,
                        "flight_type": "domestic" if domestic_flight else "international",
                        "flight_class": flight_class  # Store the common flight class
                    }
                    st.session_state.current_page = "payment"
                    st.rerun()
                else:
                    st.error("Please fill in all required fields and agree to the terms and conditions.")
                    
        if st.button("← Back to Flight Search"):
            st.session_state.current_page = "main"
            st.rerun()




# integration for available seats table
def get_available_seats_by_class(flight_class):
    connection = create_mysql_connection()
    if not connection:
        return []
    
    try:
        cursor = connection.cursor(dictionary=True)
        
        # Map your flight class names to database values
        class_mapping = {
            "First Class": "First",
            "Business": "Business",
            "Economy": "Economy"
        }
        db_class = class_mapping.get(flight_class, "Economy")
        
        query = """
        SELECT CONCAT(row_num, seat_letter) AS seat_number 
        FROM available_seats 
        WHERE class_type = %s AND is_available = 1
        ORDER BY row_num, seat_letter
        """
        cursor.execute(query, (db_class,))
        seats = [seat['seat_number'] for seat in cursor.fetchall()]
        return seats
        
    except Error as e:
        st.error(f"Error fetching seats: {e}")
        return []
    finally:
        if connection.is_connected():
            cursor.close()
            connection.close()
    




def payment_page():
    # Load Font Awesome
    st.markdown(
        '<link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css" rel="stylesheet">',
        unsafe_allow_html=True
    )
    st.markdown(
        '<h1><i class="fa-solid fa-list-check"></i> Payment & Booking Summary</h1>',
        unsafe_allow_html=True
    )
    
    # Custom CSS for better styling
    st.markdown("""
    <style>
        .summary-card {
            background-color: white;
            border-radius: 10px;
            padding: 20px;
            margin-bottom: 20px;
            box-shadow: 0 4px 8px rgba(0,0,0,0.1);
        }
        .passenger-row {
            display: flex;
            justify-content: space-between;
            padding: 10px 0;
            border-bottom: 1px solid #eee;
        }
        .total-row {
            font-weight: bold;
            font-size: 1.1em;
            color: #2e7d32;
        }
    </style>
    """, unsafe_allow_html=True)
    
    
    
    # Get flight details
    flight_list = st.session_state.get(st.session_state.selected_flight_source, [])
    flight = flight_list[st.session_state.selected_flight_index]
    
    itinerary = flight["itineraries"][0]
    first_segment = itinerary["segments"][0]
    last_segment = itinerary["segments"][-1]
    airline_code = first_segment["carrierCode"]
    flight_code = f"{airline_code}{first_segment['number']}"
    
    # Get the exact class prices from session state
    if 'flight_class_prices' not in st.session_state:
        st.error("Flight pricing data missing! Please start over.")
        st.button("← Back to Home", on_click=lambda: setattr(st.session_state, "current_page", "main"))
        return
    
    class_prices = st.session_state.flight_class_prices
    
    # Display flight summary
    st.markdown(
        '<h3 style="color:#154c79;">• Flight Details</h3>',
        unsafe_allow_html=True
    )
    with st.container():
        st.markdown(f"""
        <div class="summary-card">
            <div style="display: flex; justify-content: space-between; align-items: center;">
                <div>
                    <h3 style="margin-top: 0;">{AIRLINE_NAME_MAPPING.get(airline_code, airline_code)} {flight_code}</h3>
                    <p><strong>Route:</strong> {first_segment['departure']['iataCode']} → {last_segment['arrival']['iataCode']}</p>
                    <p><strong>Departure:</strong> {format_date(first_segment['departure']['at'])} at {format_time(first_segment['departure']['at'])}</p>
                    <p><strong>Arrival:</strong> {format_date(last_segment['arrival']['at'])} at {format_time(last_segment['arrival']['at'])}</p>
                </div>
                <div style="text-align: right;">
                    <p><strong>Duration:</strong> {itinerary['duration'].replace("PT", "").lower()}</p>
                    <p><strong>Flight Type:</strong> {'Return' if st.session_state.selected_flight_source == 'return_flights' else 'Outbound'}</p>
                </div>
            </div>
        </div>
        """, unsafe_allow_html=True)


    # Display selected offer if available
    if 'selected_offer' in st.session_state and st.session_state.selected_offer:
        offer = st.session_state.selected_offer
        st.markdown(
            '<h3 style="color:#154c79;">• Selected Offer</h3>',
            unsafe_allow_html=True
        )
        st.markdown(f"""
        <div class="summary-card">
            <div style="display: flex; align-items: center; gap: 15px;">
                <div style="
                    background-color: {offer['color']};
                    width: 10px;
                    height: 50px;
                    border-radius: 5px;
                "></div>
                <div>
                    <h4 style="margin: 0;">{offer['title']}</h4>
                    <p style="margin: 5px 0 0 0; color: #666;">Applied to your booking</p>
                </div>
            </div>
        </div>
        """, unsafe_allow_html=True)
    
    # Display passenger details and pricing
    st.markdown(
        '<h3 style="color:#154c79;">• Passenger Details</h3>',
        unsafe_allow_html=True
    )

    with st.container():
        st.markdown("""
        <style>
            .summary-card {
                background-color: white;
                border-radius: 10px;
                padding: 20px;
                margin-bottom: 20px;
                box-shadow: 0 4px 8px rgba(0,0,0,0.1);
            }
            .pricing-grid {
                display: grid;
                grid-template-columns: 2fr 1fr 1fr;
                margin-bottom: 10px;
            }
            .pricing-row {
                display: grid;
                grid-template-columns: 2fr 1fr 1fr;
                padding: 10px 0;
                border-bottom: 1px solid #eee;
                align-items: center;
            }
            .pricing-name {
                word-wrap: break-word;
                padding-right: 10px;
            }
            .pricing-value {
                text-align: right;
            }
            .subtotal-row {
                font-weight: bold;
                border-top: 2px solid #eee;
                border-bottom: 2px solid #eee;
            }
            .total-row {
                font-weight: bold;
                font-size: 1.1em;
                color: #2e7d32;
                background-color: #f5faf5;
                border-radius: 8px;
                padding: 10px 0;
            }
            .tax-row {
                font-size: 0.9em;
                color: #666;
            }
        </style>
        """, unsafe_allow_html=True)

        st.markdown("""
        <div class="summary-card">
            <div class="pricing-grid">
                <div><strong>Passenger</strong></div>
                <div><strong>Class</strong></div>
                <div style="text-align: right;"><strong>Price</strong></div>
            </div>
        """, unsafe_allow_html=True)

        # Calculate base fares
        base_fare = 0
        passengers = st.session_state.passenger_details.get("passengers", [])
        
        if not passengers:
            st.error("No passenger data found! Please start over.")
        else:
            for i, passenger in enumerate(passengers, 1):
                passenger_class = passenger.get("flight_class")
                if passenger_class not in class_prices:
                    st.error(f"Invalid flight class for passenger {i}")
                    continue
                
                passenger_price = class_prices[passenger_class]
                base_fare += passenger_price
                
                st.markdown(f"""
                <div class="pricing-row">
                    <div class="pricing-name">
                        {i}. {passenger.get('first_name', '')} {passenger.get('last_name', '')}
                    </div>
                    <div>{passenger_class}</div>
                    <div class="pricing-value">₹{passenger_price:,.2f}</div>
                </div>
                """, unsafe_allow_html=True)

            # Calculate taxes and fees (sample calculations - adjust as needed)
            passenger_count = len(passengers)
            airport_tax = 850 * passenger_count
            fuel_surcharge = 1200 * passenger_count
            gst = base_fare * 0.05  # 5% GST
            convenience_fee = 199 if passenger_count < 3 else 299
            total_taxes = airport_tax + fuel_surcharge + gst + convenience_fee
            total_amount = base_fare + total_taxes

            # Display subtotal
            st.markdown(f"""
            <div class="pricing-row subtotal-row">
                <div>Base Fare</div>
                <div></div>
                <div class="pricing-value">₹{base_fare:,.2f}</div>
            </div>
            """, unsafe_allow_html=True)

            # Display taxes and fees breakdown
            st.markdown("""
            <div style="margin: 15px 0 5px 0; font-weight: bold;">
                Taxes & Fees
            </div>
            """, unsafe_allow_html=True)

            st.markdown(f"""
            <div class="pricing-row tax-row">
                <div>Airport Tax</div>
                <div>{passenger_count} × ₹850</div>
                <div class="pricing-value">₹{airport_tax:,.2f}</div>
            </div>
            <div class="pricing-row tax-row">
                <div>Fuel Surcharge</div>
                <div>{passenger_count} × ₹1,200</div>
                <div class="pricing-value">₹{fuel_surcharge:,.2f}</div>
            </div>
            <div class="pricing-row tax-row">
                <div>GST (5%)</div>
                <div></div>
                <div class="pricing-value">₹{gst:,.2f}</div>
            </div>
            <div class="pricing-row tax-row">
                <div>Convenience Fee</div>
                <div></div>
                <div class="pricing-value">₹{convenience_fee:,.2f}</div>
            </div>
            """, unsafe_allow_html=True)

            # Display total amount
            st.markdown(f"""
            <div class="pricing-row total-row" style="margin-top: 15px;">
                <div>Total Payable Amount</div>
                <div></div>
                <div class="pricing-value">₹{total_amount:,.2f}</div>
            </div>
            </div>
            """, unsafe_allow_html=True)

            # Store the calculated total in session state
            st.session_state.total_amount = total_amount

    
    # Display contact information
    st.markdown(
        '<h3 style="color:#154c79;">• Contact Information</h3>',
        unsafe_allow_html=True
    )
    with st.container():
        contact = st.session_state.passenger_details.get("contact", {})
        st.markdown(f"""
        <div class="summary-card">
            <p><strong>Email:</strong> {contact.get('email', 'Not provided')}</p>
            <p><strong>Phone:</strong> {contact.get('phone', 'Not provided')}</p>
            <p><strong>Payment Method:</strong> {st.session_state.passenger_details.get('payment_method', 'Not specified')}</p>
        </div>
        """, unsafe_allow_html=True)
    


    # Add seat selection section at the bottom
    st.markdown("---")
    st.subheader("Seat Selection")

    # Get the selected flight class from passenger details
    flight_class = st.session_state.passenger_details.get("flight_class", "Economy")

    # Ask user if they want to select seats now
    seat_selection = st.radio(
        "Would you like to select your seats now?",
        ["Yes, select seats now", "No, assign me seats automatically"],
        index=0,
        key="seat_selection"
    )

    if seat_selection == "Yes, select seats now":
        st.info("Please select your preferred seats from the map below:")

        # Get available seats from database
        available_seats = get_available_seats_by_class(flight_class)

        if not available_seats:
            st.warning("No available seats found for this class. Seats will be assigned automatically.")
        else:
            try:
                # Load appropriate seat map image based on class
                seat_map_image = {
                    "First Class": "FirstClassSeats.png",
                    "Business": "BusinessClassSeats.png",
                    "Economy": "EconomyClassSeats.png"
                }.get(flight_class, "EconomyClassSeats.png")

                seat_map = Image.open(seat_map_image)

                # Create popover for seat map
                with st.popover(f"👁‍🗨 View {flight_class} Seat Map"):
                    st.image(seat_map, use_container_width=True)

                # Seat selection form
                with st.form("seat_selection_form"):
                    selected_seats = []
                    seat_choices = available_seats.copy()

                    for i in range(1, st.session_state.passengers + 1):
                        passenger_name = f"{st.session_state.passenger_details['passengers'][i-1]['first_name']} {st.session_state.passenger_details['passengers'][i-1]['last_name']}"
                        seat = st.selectbox(
                            f"Select seat for Passenger {i}: {passenger_name}",
                            seat_choices,
                            key=f"seat_{i}"
                        )
                        selected_seats.append(seat)

                    if st.form_submit_button("Confirm Seat Selection"):
                        # Check for duplicate seats
                        if len(set(selected_seats)) != len(selected_seats):
                            st.warning("Seat already selected for another passenger. Please select different seats.")
                        else:
                            st.session_state.selected_seats = selected_seats
                            st.success(f"Seats selected: {', '.join(selected_seats)}")

            except FileNotFoundError:
                st.warning(f"Seat map image not found. Seats will be assigned automatically.")
    else :
        st.info("Seats will be assigned automatically during check-in.")

                            
        


    # Payment and navigation buttons
    col1, col2 = st.columns(2)
    with col1:
        if st.button("← Back to Passenger Details", use_container_width=True):
            # Don't reset any data, just go back
            st.session_state.current_page = "passenger_details"
            st.rerun()
    
    with col2:
        if st.button("Confirm Booking & Pay", type="primary", use_container_width=True):
            if 'selected_seats' in st.session_state:
                if mark_seats_as_booked(st.session_state.selected_seats):
                    st.success("Booking confirmed! Thank you for your purchase.")
                    st.session_state.current_page = "booking_confirmation"
                    st.rerun()
                else:
                    st.error("Failed to book seats. Please try again.")
            else:
                st.success("Booking confirmed! Thank you for your purchase.")
                st.session_state.current_page = "booking_confirmation"
                st.rerun()




def create_booking_in_db():
    connection = None
    try:
        connection = create_mysql_connection()
        if not connection:
            st.error("Failed to connect to database")
            return None
            
        cursor = connection.cursor(dictionary=True)

        # First check if this booking already exists
        if 'passenger_details' in st.session_state:
            email = st.session_state.passenger_details.get("contact", {}).get("email")
            flight_list = st.session_state.get(st.session_state.selected_flight_source, [])
            
            if flight_list and st.session_state.selected_flight_index < len(flight_list):
                flight = flight_list[st.session_state.selected_flight_index]
                itinerary = flight["itineraries"][0]
                first_segment = itinerary["segments"][0]
                flight_number = f"{first_segment['carrierCode']}{first_segment['number']}"
                departure_time = first_segment['departure']['at']
                
                check_query = """
                SELECT b.booking_reference 
                FROM bookings b
                JOIN flights f ON b.booking_id = f.booking_id
                WHERE b.contact_email = %s 
                AND f.flight_number = %s 
                AND f.departure_datetime = %s
                LIMIT 1
                """
                cursor.execute(check_query, (email, flight_number, departure_time))
                existing = cursor.fetchone()
                
                if existing:
                    return existing['booking_reference']
        
        # Generate a unique booking reference
        booking_ref = f"SB-{uuid.uuid4().hex[:8].upper()}"
        
        # Get passenger details from session state
        passenger_details = st.session_state.passenger_details
        contact_info = passenger_details.get("contact", {})
        
        # Insert into bookings table
        booking_query = """
        INSERT INTO bookings (
            booking_reference, 
            total_amount, 
            payment_method, 
            contact_email, 
            contact_phone, 
            flight_type
        ) VALUES (%s, %s, %s, %s, %s, %s)
        """
        cursor.execute(booking_query, (
            booking_ref,
            st.session_state.total_amount,
            passenger_details.get("payment_method", "Credit Card"),
            contact_info.get("email", ""),
            contact_info.get("phone", ""),
            "round-trip" if st.session_state.get("return_flights") else "one-way"
        ))
        booking_id = cursor.lastrowid
        
        # Insert flight details
        flight_list = st.session_state.get(st.session_state.selected_flight_source, [])
        if flight_list and st.session_state.selected_flight_index < len(flight_list):
            flight = flight_list[st.session_state.selected_flight_index]
            itinerary = flight["itineraries"][0]
            first_segment = itinerary["segments"][0]
            last_segment = itinerary["segments"][-1]
            
            flight_query = """
            INSERT INTO flights (
                booking_id,
                flight_number,
                airline_code,
                origin_code,
                destination_code,
                departure_datetime,
                arrival_datetime,
                duration,
                flight_class
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """
            cursor.execute(flight_query, (
                booking_id,
                f"{first_segment['carrierCode']}{first_segment['number']}",
                first_segment['carrierCode'],
                first_segment['departure']['iataCode'],
                last_segment['arrival']['iataCode'],
                first_segment['departure']['at'],
                last_segment['arrival']['at'],
                itinerary['duration'],
                st.session_state.passenger_details.get("flight_class", "Economy")
            ))
        
        # Insert passenger details with seat assignments
        passengers = passenger_details.get("passengers", [])
        selected_seats = st.session_state.get("selected_seats", [])
        
        for i, passenger in enumerate(passengers):
            passenger_query = """
            INSERT INTO passengers (
                booking_id,
                first_name,
                last_name,
                gender,
                dob,
                passport_number,
                nationality,
                flight_class,
                seat_assigned
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """
            
            # Get the seat for this passenger if it exists
            seat_assigned = selected_seats[i] if i < len(selected_seats) else None
            
            cursor.execute(passenger_query, (
                booking_id,
                passenger['first_name'],
                passenger['last_name'],
                passenger['gender'],
                passenger['dob'],
                passenger['passport'] if passenger['passport'] != "NOT_REQUIRED" else None,
                passenger['nationality'],
                passenger['flight_class'],
                seat_assigned
            ))
            
            # Mark seat as unavailable in available_seats table if assigned
            if seat_assigned:
                # Extract row number and seat letter (e.g., "17C" -> row=17, letter='C')
                row_num = int(''.join(filter(str.isdigit, seat_assigned)))
                seat_letter = ''.join(filter(str.isalpha, seat_assigned)).upper()
                
                update_query = """
                UPDATE available_seats 
                SET is_available = 0 
                WHERE row_num = %s AND seat_letter = %s AND class_type = %s
                """
                cursor.execute(update_query, (
                    row_num,
                    seat_letter,
                    "First" if passenger['flight_class'] == "First Class" else passenger['flight_class']
                ))
        
        # Insert offer if applied
        if 'selected_offer' in st.session_state and st.session_state.selected_offer:
            offer_query = "INSERT INTO booking_offers (booking_id, offer_title) VALUES (%s, %s)"
            cursor.execute(offer_query, (booking_id, st.session_state.selected_offer['title']))
        
        connection.commit()  # Explicit commit
        return booking_ref
        
    except Error as e:
        st.error(f"Error creating booking: {e}")
        if connection:
            connection.rollback()
        return None
    finally:
        if connection and connection.is_connected():
            cursor.close()
            connection.close()


                # ----------------------------------------------------  



def get_booking_history(email):
    """Find bookings that match current session details"""
    connection = create_mysql_connection()
    if not connection:
        return None
    
    try:
        cursor = connection.cursor(dictionary=True)
        
        # Query to get all booking details including passenger names
        query = """
        SELECT 
            b.booking_reference, 
            b.booking_date, 
            b.total_amount, 
            b.status,
            f.flight_number, 
            f.airline_code, 
            f.origin_code, 
            f.destination_code,
            f.departure_datetime, 
            f.arrival_datetime, 
            f.flight_class,
            (
                SELECT GROUP_CONCAT(CONCAT(p.first_name, ' ', p.last_name) 
                FROM passengers p 
                WHERE p.booking_id = b.booking_id
            ) AS passengers
        FROM bookings b
        JOIN flights f ON b.booking_id = f.booking_id
        WHERE b.contact_email = %s
        ORDER BY b.booking_date DESC
        LIMIT 5
        """
        
        cursor.execute(query, (email,))
        bookings = cursor.fetchall()
        
        # Ensure passengers field is properly formatted
        for booking in bookings:
            if booking['passengers'] is None:
                booking['passengers'] = "No passenger data"
        
        return bookings
        
    except Error as e:
        st.error(f"Error fetching booking history: {e}")
        return None
    finally:
        if connection.is_connected():
            cursor.close()
            connection.close()


            # ----------------------------------------------------------------


#seat status as booked
def mark_seats_as_booked(seat_numbers):
    connection = create_mysql_connection()
    if not connection:
        return False
    
    try:
        cursor = connection.cursor()
        
        # Update each seat
        for seat in seat_numbers:
            # Extract row number and seat letter from seat number (e.g., "8A" -> row=8, letter='A')
            row_num = int(''.join(filter(str.isdigit, seat)))
            seat_letter = ''.join(filter(str.isalpha, seat)).upper()
            
            query = """
            UPDATE available_seats 
            SET is_available = 0 
            WHERE row_num = %s AND seat_letter = %s
            """
            cursor.execute(query, (row_num, seat_letter))
        
        connection.commit()
        return True
        
    except Error as e:
        st.error(f"Error updating seats: {e}")
        connection.rollback()
        return False
    finally:
        if connection.is_connected():
            cursor.close()
            connection.close()

    

def booking_confirmation_page():
    st.title("✔️ Booking Confirmed!")

    def load_lottieurl(url):
        r = requests.get(url)
        if r.status_code != 200:
            return None
        return r.json()

    lottie_airplane = load_lottieurl("https://lottie.host/9a7c5716-fb1d-41d3-b99d-5feba287f19d/fH7JXuMNGi.json")
    st_lottie(lottie_airplane, key="airplane")
    
    # Check if booking already exists in session state
    if 'booking_reference' not in st.session_state:
        # Store the booking in database
        booking_ref = create_booking_in_db()
        if booking_ref:
            st.session_state.booking_reference = booking_ref
        else:
            st.error("There was an error processing your booking. Please contact customer support.")
            return
    else:
        booking_ref = st.session_state.booking_reference
    
    st.markdown(f"""
    <div style="text-align: center; padding: 40px 20px; background-color: #e8f5e9; border-radius: 10px; margin: 20px 0;">
        <h2 style="color: #2e7d32;">Your flight has been booked successfully!</h2>
        <p style="font-size: 18px;"><strong>Booking Reference:</strong> {booking_ref}</p>
        <p style="font-size: 18px;">We'll be sending your booking details to your email shortly.</p>
        <p style="font-size: 16px;">Thank you for choosing our service.</p>
    </div>
    """, unsafe_allow_html=True)
    
    if st.button("← Back to Home", type="primary"):
        # Preserve passenger details and booking reference
        passenger_details = st.session_state.get("passenger_details", {})
        booking_ref = st.session_state.get("booking_reference")
        
        reset_context()  # This now preserves email
        
        # Restore the important details
        if passenger_details:
            st.session_state.passenger_details = passenger_details
        if booking_ref:
            st.session_state.booking_reference = booking_ref
            
        st.session_state.current_page = "main"
        st.rerun()


# Modify the offers_dialog function to properly handle confirmation
@st.dialog(title="Flight Details and Offers")
def offers_dialog():
    # Create two tabs: "Offers" and "Flight Details"
    tab1, tab2 = st.tabs(["Offers", "Flight Details"])

    with tab1:
        st.write("Here are the current flight offers. Select one offer to proceed:")

        # Define offers (without flight class)
        # Updated offers list with your new offers
        offers = [
            {"title": "Early Bird Discount on Flight Bookings", "color": "#FF6F61"},
            {"title": "Priority Check-in and Boarding Service", "color": "#FFD166"},
            {"title": "Festival Season Flight Discount", "color": "#06D6A0"},
            {"title": "Exclusive Bank Card Cashback on Flight Bookings", "color": "#118AB2"},
            {"title": "Coupon Code for Flat Discount on Flight Tickets", "color": "#073B4C"},
            {"title": "Membership Program with Exclusive Flight Deals", "color": "#EF476F"},
            {"title": "Extra Baggage Allowance Offer", "color": "#8A2BE2"},  # Purple
            {"title": "Last-Minute Flight Booking Discount", "color": "#FF6347"}  # Tomato
        ]

        # Create a 2-column grid
        col1, col2 = st.columns(2)

        # Display offers as selectable cards in a 2-column grid
        selected_offer = None
        for i, offer in enumerate(offers):
            with (col1 if i % 2 == 0 else col2):
                st.markdown(
                    f"""
                    <div style="
                        background-color: {offer['color']};
                        color: white;
                        padding: 20px;
                        border-radius: 10px;
                        margin: 5px 0;
                        box-shadow: 0px 4px 6px rgba(0, 0, 0, 0.1);
                        text-align: center;
                    ">
                        <p>{offer['title']}</p>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
                if st.button("Select", key=f"select_offer_{i}"):
                    selected_offer = offer
                    st.session_state.selected_offer = selected_offer
                    st.success(f"Selected Offer: {offer['title']}")

        # Add a "Proceed Without Offer" button and a "Confirm with Offer" button
        col1, col2 = st.columns(2)
        with col1:
            if st.button("Proceed Without Offer", type="secondary"):
                st.session_state.selected_offer = None
                st.session_state.current_page = "passenger_details"
                st.rerun()
        
        with col2:
            if st.button("Confirm with Offer", type="primary"):
                if 'selected_offer' in st.session_state:
                    st.session_state.current_page = "passenger_details"
                    st.rerun()
                else:
                    st.warning("No offer selected. Please select an offer or click 'Proceed Without Offer'")


    with tab2:
        st.write("Here are the flight details and seat map.")

        # Check if we have the required session state variables
        if all(key in st.session_state for key in ["selected_flight_index", "selected_flight_source"]):
            # Get the correct flight list based on whether it's outbound or return
            flights = st.session_state.get(st.session_state.selected_flight_source, [])
            
            if flights and 0 <= st.session_state.selected_flight_index < len(flights):
                selected_flight = flights[st.session_state.selected_flight_index]
                itinerary = selected_flight["itineraries"][0]
                first_segment = itinerary["segments"][0]
                last_segment = itinerary["segments"][-1]
                airline_code = first_segment["carrierCode"]
                
                # Flight Route Details Card
                st.markdown(
                    f"""
                    <style>
                        .route-card {{
                            font-family: Arial, sans-serif;
                            background-color: #ffffff;
                            padding: 20px;
                            border-radius: 10px;
                            box-shadow: 0px 4px 8px rgba(0, 0, 0, 0.1);
                            max-width: 100%;
                            width: 90%;
                            margin: 0 auto;
                            border-left: 5px solid #ff8000;
                        }}
                        .route-card h2 {{
                            margin-top: 0;
                            color: #002147;
                            font-size: 22px;
                            margin-bottom: 10px;
                        }}
                        .line-container {{
                        display: flex;
                        align-items: center;
                        justify-content: space-between;
                        width: 100%;
                        max-width: 600px;
                        margin: 20px auto;
                        }}

                        .dot {{
                        width: 10px;
                        height: 10px;
                        background-color: #ff8000;
                        border-radius: 50%;
                        }}

                        .line {{
                        flex-grow: 1;
                        height: 2px;
                        background-color: #ff8000;
                        margin: 0 2px;
                        }}
                        .route-card p {{
                            margin: 0;
                            font-size: 14px;
                            line-height: 1.6;
                        }}
                        .route-card .details-container {{
                            display: flex;
                            justify-content: space-between;
                            align-items: center;
                            gap: 20px;
                        }}
                        .route-card .details-container > div {{
                            flex: 1;
                        }}
                        .route-card .details-container .center {{
                            text-align: center;
                        }}
                        .route-card .details-container .right {{
                            text-align: right;
                        }}
                    </style>
                    <div class="route-card">
                        <h2>{first_segment['departure']['iataCode']} → {last_segment['arrival']['iataCode']}</h2>
                        <div class="line-container">
                            <div class="dot"></div>
                            <div class="line"></div>
                            <div class="dot"></div>
                        </div>
                        <div class="details-container">
                            <div>
                                <p><strong>Departure:</strong></p>
                                <p>{format_date(first_segment['departure']['at'])}</p>
                                <p>{format_time(first_segment['departure']['at'])}</p>
                                <p>Terminal {first_segment['departure'].get('terminal', 'N/A')}</p>
                            </div>
                            <div class="center">
                                <p><strong>Duration:</strong></p>
                                <p style="font-size: 16px; font-weight: bold; color: #ff8000;">{itinerary['duration'].replace("PT", "").lower()}</p>
                            </div>
                            <div class="right">
                                <p><strong>Arrival:</strong></p>
                                <p>{format_date(last_segment['arrival']['at'])}</p>
                                <p>{format_time(last_segment['arrival']['at'])}</p>
                                <p>Terminal {last_segment['arrival'].get('terminal', 'N/A')}</p>
                            </div>
                        </div>
                        <p style="font-size: 18px; font-weight: bold; color: #002147; margin-top: 15px;">
                            {AIRLINE_NAME_MAPPING.get(airline_code, airline_code)} {airline_code}{first_segment['number']}
                        </p>
                        <p style="font-size: 14px; color: #555;">
                            Flight Type: {'Return' if st.session_state.selected_flight_source == 'return_flights' else 'Outbound'}
                        </p>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
            else:
                st.warning("Selected flight data is not available. Please try selecting again.")
        else:
            st.warning("No flight selected or flight data is unavailable.")

        # Display seat map
        st.markdown("### Seat Map")
        try:
            image = Image.open("New_whiteSeatMap.jpg")
            st.image(
                image,
                caption="Seat Map",
                use_container_width=True,
                output_format="PNG",
            )
        except FileNotFoundError:
            st.warning("Seat map image not found.")


# Function to render flight cards with random prices for different classes
def render_flight_cards(flights, trip_type="Outbound"):
    for idx, flight in enumerate(flights):
        itinerary = flight["itineraries"][0]
        segments = itinerary["segments"]
        num_stops = len(segments) - 1
        stops_text = (
            f'<i class="fas fa-plane" style="color:#154c79;"></i> Nonstop' 
            if num_stops == 0 
            else f'<i class="fas fa-clock" style="color:#154c79;"></i> {num_stops} Stop{"s" if num_stops > 1 else ""}'
        )
        first_segment = segments[0]
        last_segment = segments[-1]
        airline_code = first_segment["carrierCode"]
        flight_code = f"{airline_code}{first_segment['number']}"
        airline_name = AIRLINE_NAME_MAPPING.get(airline_code, airline_code)

        # Airline Logo URL
        airline_logo_url = f"https://www.gstatic.com/flights/airline_logos/70px/{airline_code}.png"

        stopover_cities = ", ".join(seg["arrival"]["iataCode"] for seg in segments[:-1]) if num_stops > 0 else "None"
        duration = itinerary["duration"].replace("PT", "").lower()

        departure_time = format_time(first_segment["departure"]["at"])
        arrival_time = format_time(last_segment["arrival"]["at"])
        departure_date = format_date(first_segment["departure"]["at"])  # Departure date
        arrival_date = format_date(last_segment["arrival"]["at"])      # Arrival date
        departure_terminal = first_segment["departure"].get("terminal", "N/A")
        arrival_terminal = last_segment["arrival"].get("terminal", "N/A")

        # Generate random prices for different classes (per passenger)
        num_passengers = st.session_state.get("passengers", 1)
        total_price = float(flight['price']['total'])
        price_per_passenger = total_price / num_passengers  # Calculate per-passenger price first
        # Calculate exact prices (same as shown in flight card)
        class_prices = {
            "Economy": price_per_passenger,
            "Business": round(price_per_passenger * 1.8, 2),
            "First Class": round(price_per_passenger * 3.2, 2)
        }
        
        # Store these prices in session state when flight is selected
        if idx == st.session_state.get("selected_flight_index", -1) and trip_type.lower() == st.session_state.get("selected_trip_type", "").lower():
            st.session_state.flight_class_prices = class_prices

        # Main card content
        st.markdown(
            f"""
            <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.2/css/all.min.css">
            <div class="flight-card" style="background-color:white; color:black; padding:10px; border-radius:8px; box-shadow:0px 4px 8px rgba(0, 0, 0, 0.1);">
                <div style="display:flex; align-items:center; justify-content:space-between;">
                    <div style="display:flex; align-items:center; gap:10px;">
                        <img src="{airline_logo_url}" alt="{airline_name}" style="width:60px; height:auto; border-radius:8px;">
                        <div>
                            <h3 style="margin:0; font-size:16px;">{airline_name} ({flight_code})</h3>
                            <p style="margin:0; font-size:12px; opacity:0.9;">{trip_type} Flight</p>
                        </div>
                    </div>
                    <h2 style="color:#154c79; margin:0;"><i class="fas fa-indian-rupee-sign" style="color:#154c79;"></i> {price_per_passenger}</h2>
                </div>
                <hr style="border: 0; height: 1px; background: rgba(169, 169, 169, 1); margin: 10px 0;">
                <div style="display: flex; justify-content: space-between;">
                    <div style="flex: 1; border-right: 1px solid rgba(169, 169, 169, 1); padding-right: 10px;">
                        <p style="font-size: 14px; font-weight: bold;"><i class="fas fa-plane-departure" style="color:#154c79;"></i> {first_segment['departure']['iataCode']} ({departure_time})</p>
                        <p style="font-size: 12px;"><strong><i class="fas fa-calendar-day" style="color:#154c79;"></i> Departure Date:</strong> {departure_date}</p>
                        <p style="font-size: 12px;"><strong><i class="fas fa-map-marker-alt" style="color:#154c79;"></i> Terminal:</strong> {departure_terminal}</p>
                    </div>
                    <div style="flex: 1; text-align: center; border-right: 1px solid rgba(169, 169, 169, 1); padding-right: 10px;">
                        <p style="font-size: 14px;"><strong><i class="fas fa-hourglass-half" style="color:#154c79;"></i> Duration:</strong> {duration}</p>
                        <p style="font-size: 14px;"><strong>{stops_text}</strong></p>
                        <p style="font-size: 12px;"><strong><i class="fas fa-city" style="color:#154c79;"></i> Layovers:</strong> {stopover_cities}</p>
                    </div>
                    <div style="flex: 1; text-align: right;">
                        <p style="font-size: 14px; font-weight: bold;"><i class="fas fa-plane-arrival" style="color:#154c79;"></i> {last_segment['arrival']['iataCode']} ({arrival_time})</p>
                        <p style="font-size: 12px;"><strong><i class="fas fa-calendar-day" style="color:#154c79;"></i> Arrival Date:</strong> {arrival_date}</p>
                        <p style="font-size: 12px;"><strong><i class="fas fa-map-marker-alt" style="color:#154c79;"></i> Terminal:</strong> {arrival_terminal}</p>
                    </div>
                </div>
                <hr style="border: 0; height: 1px; background: rgba(169, 169, 169, 1); margin: 10px 0;">
                <div style="display: flex; justify-content: space-around; text-align: center;">
                    <div>
                        <p style="font-size: 14px; font-weight: bold; color:#154c79;"><i class="fas fa-coins" style="color:#154c79;"></i> Economy</p>
                        <p style="font-size: 12px;">₹ {class_prices["Economy"]:.2f}</p>
                    </div>
                    <div>
                        <p style="font-size: 14px; font-weight: bold; color:#154c79;"><i class="fas fa-business-time" style="color:#154c79;"></i> Business</p>
                        <p style="font-size: 12px;">₹ {class_prices["Business"]:.2f}</p>
                    </div>
                    <div>
                        <p style="font-size: 14px; font-weight: bold; color:#154c79;"><i class="fas fa-crown" style="color:#154c79;"></i> First Class</p>
                        <p style="font-size: 12px;">₹ {class_prices["First Class"]:.2f}</p>
                    </div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        st.markdown("""
                <style>
                    [data-testid="baseButton-primary"] {
                        margin-top: 10px;
                    }
                </style>
            """, unsafe_allow_html=True)
        if st.button("View Details and Offers", key=f"view_details_offers_{flight_code}{trip_type}{idx}", type="primary"):
            st.session_state.selected_flight_index = idx
            st.session_state.selected_trip_type = trip_type
            # Store whether this is an outbound or return flight
            st.session_state.selected_flight_source = "flights" if trip_type == "Outbound" else "return_flights"
            st.session_state.flight_class_prices = class_prices  # Store the exact prices
            offers_dialog()
            

# Initialize session state for page navigation
if "current_page" not in st.session_state:
    st.session_state.current_page = "main"



# Add this function to handle speech-to-text conversion
def recognize_speech():
    recognizer = sr.Recognizer()
    with sr.Microphone() as source:
        st.write("Listening... Speak now!")
        audio = recognizer.listen(source)
        try:
            text = recognizer.recognize_google(audio)  # Use Google Web Speech API
            st.write(f"You said: {text}")
            return text
        except sr.UnknownValueError:
            st.error("Sorry, I could not understand the audio.")
            return None
        except sr.RequestError:
            st.error("Sorry, there was an issue with the speech recognition service.")
            return None


# ----------------------------------------------

def find_bookings_by_session():
    """Find bookings that match current session details"""
    connection = create_mysql_connection()
    if not connection:
        return None
    
    try:
        cursor = connection.cursor(dictionary=True)
        
        # Try to find matching bookings based on available session info
        query = """
        SELECT DISTINCT b.booking_reference, b.booking_date, b.total_amount, b.status,
               f.flight_number, f.airline_code, f.origin_code, f.destination_code,
               f.departure_datetime, f.arrival_datetime, f.flight_class
        FROM bookings b
        JOIN flights f ON b.booking_id = f.booking_id
        """
        
        # Add conditions based on what session info we have
        conditions = []
        params = []
        
        if "passenger_details" in st.session_state:
            email = st.session_state.passenger_details.get("contact", {}).get("email")
            if email:
                conditions.append("b.contact_email = %s")
                params.append(email)
        
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        
        query += " ORDER BY b.booking_date DESC"
        
        cursor.execute(query, tuple(params))
        return cursor.fetchall()
        
    except Error as e:
        st.error(f"Error finding bookings: {e}")
        return None
    finally:
        if connection.is_connected():
            cursor.close()
            connection.close()


# --------------------------

def generate_ticket_pdf(booking_details):
    """Generate a PDF e-ticket for the booking"""
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter
    
    # Add logo (you can replace with your own logo)
    try:
        logo = ImageReader("https://cdn-icons-png.flaticon.com/512/187/187820.png")
        c.drawImage(logo, 30, height - 100, width=60, height=60, preserveAspectRatio=True)
    except:
        pass
    
    # Add header
    c.setFont("Helvetica-Bold", 16)
    c.drawString(100, height - 80, "E-Ticket / Boarding Pass")
    c.setFont("Helvetica", 10)
    c.drawString(100, height - 100, f"Booking Reference: {booking_details['booking_reference']}")
    
    # Flight details
    c.setFont("Helvetica-Bold", 12)
    c.drawString(50, height - 140, "Flight Details")
    c.setFont("Helvetica", 10)
    
    y = height - 160
    c.drawString(50, y, f"Airline: {AIRLINE_NAME_MAPPING.get(booking_details['airline_code'], booking_details['airline_code'])}")
    y -= 20
    c.drawString(50, y, f"Flight Number: {booking_details['flight_number']}")
    y -= 20
    c.drawString(50, y, f"From: {booking_details['origin_code']} ({format_date(booking_details['departure_datetime'])})")
    y -= 20
    c.drawString(50, y, f"To: {booking_details['destination_code']} ({format_date(booking_details['arrival_datetime'])})")
    y -= 20
    c.drawString(50, y, f"Departure: {format_time(booking_details['departure_datetime'])}")
    y -= 20
    c.drawString(50, y, f"Arrival: {format_time(booking_details['arrival_datetime'])}")
    y -= 20
    c.drawString(50, y, f"Class: {booking_details['flight_class']}")
    
    # Passenger details
    y -= 40
    c.setFont("Helvetica-Bold", 12)
    c.drawString(50, y, "Passenger Details")
    c.setFont("Helvetica", 10)
    
    for i, passenger in enumerate(booking_details['passengers'], 1):
        y -= 20
        c.drawString(50, y, f"Passenger {i}: {passenger['first_name']} {passenger['last_name']}")
        y -= 15
        c.drawString(70, y, f"Seat: {passenger.get('seat_assigned', 'To be assigned at check-in')}")
        y -= 15
        c.drawString(70, y, f"Ticket Number: {booking_details['booking_reference']}-{i}")
    
    # Footer
    y -= 40
    c.setFont("Helvetica", 8)
    c.drawString(50, y, "Thank you for choosing our service!")
    y -= 15
    c.drawString(50, y, "Please present this e-ticket at the airport check-in counter.")
    
    c.save()
    buffer.seek(0)
    return buffer


# -----------------------------

def cancel_booking(booking_reference):
    """Cancel a booking and free up seats"""
    connection = create_mysql_connection()
    if not connection:
        return False
    
    try:
        cursor = connection.cursor(dictionary=True)
        
        # 1. Get all seat assignments for this booking
        cursor.execute("""
        SELECT seat_assigned, flight_class 
        FROM passengers 
        WHERE booking_id = (SELECT booking_id FROM bookings WHERE booking_reference = %s)
        """, (booking_reference,))
        seat_assignments = cursor.fetchall()
        
        # 2. Free up the seats in available_seats table
        for assignment in seat_assignments:
            if assignment['seat_assigned']:
                # Extract row number and seat letter (e.g., "17C" -> row=17, letter='C')
                seat = assignment['seat_assigned']
                row_num = int(''.join(filter(str.isdigit, seat)))
                seat_letter = ''.join(filter(str.isalpha, seat)).upper()
                
                # Update seat availability
                cursor.execute("""
                UPDATE available_seats 
                SET is_available = 1 
                WHERE row_num = %s AND seat_letter = %s AND class_type = %s
                """, (
                    row_num,
                    seat_letter,
                    "First" if assignment['flight_class'] == "First Class" else assignment['flight_class']
                ))
        
        # 3. Remove seat assignments from passengers table
        cursor.execute("""
        UPDATE passengers 
        SET seat_assigned = NULL 
        WHERE booking_id = (SELECT booking_id FROM bookings WHERE booking_reference = %s)
        """, (booking_reference,))
        
        # 4. Update booking status to cancelled
        cursor.execute("""
        UPDATE bookings 
        SET status = 'cancelled' 
        WHERE booking_reference = %s
        """, (booking_reference,))
        
        connection.commit()
        return True
        
    except Error as e:
        st.error(f"Error cancelling booking: {e}")
        connection.rollback()
        return False
    finally:
        if connection.is_connected():
            cursor.close()
            connection.close()

# ---------------------------------------------



def main_page():
    # Streamlit App
    st.title("✈️ Hi, I'm SafarBot")

    # Initialize fresh conversation if needed
    if "conversation" not in st.session_state:
        st.session_state.conversation = [{"role": "assistant", "content": "How can I help you today? (For ex. Find flight from (origin) to (destination) on (date) by (airline_name - optional))"}]

    if "flight_params" not in st.session_state:
        st.session_state.flight_params = {}

    if "context" not in st.session_state:
        st.session_state.context = {}

    if "search_triggered" not in st.session_state:
        st.session_state.search_triggered = False

    with st.sidebar:
        st.subheader("Your Booking History")
        
        # Try to get user email from multiple possible sources
        user_email = None
        if "passenger_details" in st.session_state:
            user_email = st.session_state.passenger_details.get("contact", {}).get("email")
        elif "booking_reference" in st.session_state:
            # If we have a booking reference but no email in session, try to get it from DB
            connection = create_mysql_connection()
            if connection:
                try:
                    cursor = connection.cursor(dictionary=True)
                    cursor.execute(
                        "SELECT contact_email FROM bookings WHERE booking_reference = %s",
                        (st.session_state.booking_reference,)
                    )
                    result = cursor.fetchone()
                    if result:
                        user_email = result['contact_email']
                except Error as e:
                    st.error(f"Error fetching email: {e}")
                finally:
                    if connection.is_connected():
                        connection.close()
        
        connection = create_mysql_connection()
        if connection:
            try:
                cursor = connection.cursor(dictionary=True)
                
                if user_email:
                    query = """
                    SELECT 
                        b.booking_reference, 
                        b.booking_date, 
                        b.total_amount, 
                        b.status,
                        f.flight_number, 
                        f.airline_code, 
                        f.origin_code, 
                        f.destination_code,
                        f.departure_datetime, 
                        f.arrival_datetime, 
                        f.flight_class,
                        (
                            SELECT GROUP_CONCAT(CONCAT(p.first_name, ' ', p.last_name) SEPARATOR ', ')
                            FROM passengers p 
                            WHERE p.booking_id = b.booking_id
                        ) AS passengers
                    FROM bookings b
                    JOIN flights f ON b.booking_id = f.booking_id
                    WHERE b.contact_email = %s
                    ORDER BY b.booking_date DESC
                    """
                    cursor.execute(query, (user_email,))
                else:
                    # Show recent bookings even if no user email is available
                    query = """
                    SELECT 
                        b.booking_reference, 
                        b.booking_date, 
                        b.total_amount, 
                        b.status,
                        f.flight_number, 
                        f.airline_code, 
                        f.origin_code, 
                        f.destination_code,
                        f.departure_datetime, 
                        f.arrival_datetime, 
                        f.flight_class,
                        (
                            SELECT GROUP_CONCAT(CONCAT(p.first_name, ' ', p.last_name) SEPARATOR ', ')
                            FROM passengers p 
                            WHERE p.booking_id = b.booking_id
                        ) AS passengers
                    FROM bookings b
                    JOIN flights f ON b.booking_id = f.booking_id
                    ORDER BY b.booking_date DESC
                    """
                    cursor.execute(query)
                
                bookings = cursor.fetchall()
                
                if bookings:
                    for booking in bookings:
                        # Ensure passengers field is properly formatted
                        passengers = booking['passengers'] if booking['passengers'] else "No passenger data"
                        
                        with st.expander(f"{format_date(booking['booking_date'])} - {booking['booking_reference']}"):
                            st.markdown(f"""
                            **Flight:** {AIRLINE_NAME_MAPPING.get(booking['airline_code'], booking['airline_code'])} {booking['flight_number']}
                            - **Route:** {booking['origin_code']} → {booking['destination_code']}
                            - **Departure:** {format_date(booking['departure_datetime'])} at {format_time(booking['departure_datetime'])}
                            - **Arrival:** {format_date(booking['arrival_datetime'])} at {format_time(booking['arrival_datetime'])}
                            - **Class:** {booking['flight_class']}
                            - **Passengers:** {passengers}
                            - **Amount:** ₹{booking['total_amount']:,.2f}
                            - **Status:** {booking['status']}
                            """)


                            # Add download ticket button for confirmed bookings
                            if booking['status'] == 'confirmed':
                                # Fetch complete booking details including passengers
                                connection = create_mysql_connection()
                                if connection:
                                    try:
                                        cursor = connection.cursor(dictionary=True)

                                        # Get flight details
                                        cursor.execute("""
                                            SELECT * FROM flights 
                                            WHERE booking_id = (SELECT booking_id FROM bookings WHERE booking_reference = %s)
                                        """, (booking['booking_reference'],))
                                        flight_details = cursor.fetchone()

                                        # Get passenger details
                                        cursor.execute("""
                                            SELECT first_name, last_name, seat_assigned 
                                            FROM passengers 
                                            WHERE booking_id = (SELECT booking_id FROM bookings WHERE booking_reference = %s)
                                        """, (booking['booking_reference'],))
                                        passenger_details = cursor.fetchall()

                                        if flight_details and passenger_details:
                                            # Combine all details
                                            full_details = {
                                                'booking_reference': booking['booking_reference'],
                                                'airline_code': flight_details['airline_code'],
                                                'flight_number': flight_details['flight_number'],
                                                'origin_code': flight_details['origin_code'],
                                                'destination_code': flight_details['destination_code'],
                                                'departure_datetime': flight_details['departure_datetime'],
                                                'arrival_datetime': flight_details['arrival_datetime'],
                                                'flight_class': flight_details['flight_class'],
                                                'departure_terminal': flight_details.get('departure_terminal', 'N/A'),
                                                'passengers': passenger_details
                                            }

                                            # Generate PDF buffer
                                            pdf_buffer = generate_ticket_pdf(full_details)

                                            # Single download button
                                            st.download_button(
                                                label="Download E-Ticket",
                                                icon=":material/picture_as_pdf:",
                                                help="Download e-ticket for all passengers",
                                                data=pdf_buffer,
                                                file_name=f"e-ticket_{booking['booking_reference']}.pdf",
                                                mime="application/pdf",
                                                key=f"download_{booking['booking_reference']}"
                                            )
                                        else:
                                            st.error("Could not retrieve booking details")

                                    except Error as e:
                                        st.error(f"Error fetching booking details: {e}")
                                    finally:
                                        if connection.is_connected():
                                            connection.close()

                            
                            # Add cancellation button if flight is in future and not already cancelled
                            departure_date = booking['departure_datetime'].date()
                            current_date = datetime.now().date()

                            if departure_date > current_date and booking['status'] == 'confirmed':
                                if st.button("Cancel Booking", 
                                            key=f"cancel_{booking['booking_reference']}",
                                            type="primary",
                                            help="Cancel this booking and free up seats"):
                                    if cancel_booking(booking['booking_reference']):
                                        st.success("Booking cancelled successfully!")
                                        st.rerun()
                                    else:
                                        st.error("Failed to cancel booking. Please try again.")
                else:
                    st.info("No bookings found")
                    
            except Error as e:
                st.error(f"Error fetching bookings: {e}")
            finally:
                if connection.is_connected():
                    connection.close()


    # Display conversation
    for message in st.session_state.conversation:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    # Initialize passenger count in session state if it doesn't exist
    if "passengers" not in st.session_state:
        st.session_state.passengers = 1

    # Add a "Speak" button for speech input
    if st.button("၊၊||၊ Speak"):
        user_input = recognize_speech()
        if user_input:
            input_text = user_input
        else:
            input_text = None
    else:
        input_text = st.chat_input("Enter your query:")

    # Process the input (either from speech or text)
    if input_text:
        # Check if the user is starting a new query
        if "find flight" in input_text.lower() or "find flights" in input_text.lower():
            reset_context()  # Reset context for a new query

        st.session_state.conversation.append({"role": "user", "content": input_text})
        with st.chat_message("user"):
            st.markdown(input_text)

        # Parse the user query and update context
        origin, destination, date, airline = parse_user_query(input_text, st.session_state.context)
        st.session_state.context.update({"origin": origin, "destination": destination, "date": date, "airline": airline})

        # Determine the type of query
        query_type = determine_query_type(origin, destination, date)

        if any(phrase in input_text.lower() for phrase in ["how to book", "booking process", "booking steps", "how does this work"]):
            st.session_state.conversation.append({"role": "assistant", "content": BOOKING_PROCESS_RESPONSE})
            with st.chat_message("assistant"):
                st.markdown(BOOKING_PROCESS_RESPONSE)
            return

        if query_type:
            # Provide a specific response based on the query type
            response = FLIGHT_BOOKING_RESPONSES.get(query_type, "I'm sorry, I couldn't understand your query. Can you please provide more details?")
            st.session_state.conversation.append({"role": "assistant", "content": response})
            with st.chat_message("assistant"):
                st.markdown(response)

            # If all details are provided, set the flight parameters
            if query_type == "all_details":
                st.session_state.flight_params = {
                    "origin": CITY_TO_IATA.get(origin, origin),
                    "destination": CITY_TO_IATA.get(destination, destination),
                    "departure_date": date,
                    "airline": airline,
                }
                st.session_state.search_triggered = False
        else:
            # Fallback to a generic response if it's not a flight booking query
            response = "I'm here to help with flight bookings. Please provide details like origin, destination, and date."
            st.session_state.conversation.append({"role": "assistant", "content": response})
            with st.chat_message("assistant"):
                st.markdown(response)

    # If flight parameters are set, show passenger and trip type options
    if st.session_state.flight_params:
        st.subheader("Flight Search Parameters")
        st.write(f"**Origin:** {st.session_state.flight_params['origin']}")
        st.write(f"**Destination:** {st.session_state.flight_params['destination']}")
        st.write(f"**Departure Date:** {st.session_state.flight_params['departure_date']}")

        passengers = st.number_input(
            "Number of Passengers", 
            min_value=1, 
            max_value=10, 
            value=st.session_state.passengers, 
            key="passengers_input",
            on_change=lambda: setattr(st.session_state, 'passengers', st.session_state.passengers_input)
        )
        trip_type = st.radio("Select Trip Type:", ["One-Way", "Round-Trip"], key="trip_type")

        return_date = None
        if trip_type == "Round-Trip":
            return_date = st.date_input("Select Return Date:", key="return_date")
            if return_date and return_date < datetime.strptime(st.session_state.flight_params["departure_date"], "%Y-%m-%d").date():
                st.warning("⚠️ Return date cannot be before the departure date. Please select a valid date.")
                return_date = None

        if st.button("Search Flights"):
            st.session_state.search_triggered = True

        if st.session_state.search_triggered:
            token = generate_access_token()
            if token:
                st.subheader("Outbound Flights")
                flights = fetch_flight_data(
                    st.session_state.flight_params["origin"],
                    st.session_state.flight_params["destination"],
                    st.session_state.flight_params["departure_date"],
                    token,
                    st.session_state.flight_params["airline"],
                    st.session_state.passengers
                )
                # Store flights in session state
                st.session_state.flights = flights

                if not flights and st.session_state.flight_params["airline"]:
                    st.warning(f"No outbound flights found for {AIRLINE_NAME_MAPPING.get(st.session_state.flight_params['airline'], st.session_state.flight_params['airline'])}. Select another airline:")
                    alternative_airline = st.selectbox("Choose an alternative airline:", list(AIRLINE_NAME_MAPPING.values()), key="alt_airline_outbound")
                    airline_code = [code for code, name in AIRLINE_NAME_MAPPING.items() if name == alternative_airline][0]
                    flights = fetch_flight_data(
                        st.session_state.flight_params["origin"],
                        st.session_state.flight_params["destination"],
                        st.session_state.flight_params["departure_date"],
                        token,
                        airline_code,
                        passengers
                    )
                # Store updated flights in session state
                st.session_state.flights = flights

                if flights:
                    render_flight_cards(flights, "Outbound")
                else:
                    st.warning("No flights found for the given criteria.")
                
                if trip_type == "Round-Trip" and return_date:
                    st.subheader("Return Flights")
                    return_flights = fetch_flight_data(
                        st.session_state.flight_params["destination"],
                        st.session_state.flight_params["origin"],
                        return_date.strftime("%Y-%m-%d"),
                        token,
                        st.session_state.flight_params["airline"],
                        passengers
                    )

                    if not return_flights:
                        st.warning(f"No return flights found for {AIRLINE_NAME_MAPPING.get(st.session_state.flight_params['airline'], st.session_state.flight_params['airline'])}. Select another airline:")
                        alternative_airline = st.selectbox("Choose an alternative airline for return:", list(AIRLINE_NAME_MAPPING.values()), key="alt_airline_return")
                        airline_code = [code for code, name in AIRLINE_NAME_MAPPING.items() if name == alternative_airline][0]
                        return_flights = fetch_flight_data(
                            st.session_state.flight_params["destination"],
                            st.session_state.flight_params["origin"],
                            return_date.strftime("%Y-%m-%d"),
                            token,
                            airline_code,
                            passengers
                        )

                    if return_flights:
                        st.session_state.return_flights = return_flights
                        render_flight_cards(return_flights, "Return")
                    else:
                        st.warning("No flights found for the given criteria.")
                

        
# Render the appropriate page based on session state
if st.session_state.current_page == "main":
    main_page()
elif st.session_state.current_page == "passenger_details":
    passenger_details_page()
elif st.session_state.current_page == "payment":
    payment_page()
elif st.session_state.current_page == "booking_confirmation":
    booking_confirmation_page()