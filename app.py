import streamlit as st
import pandas as pd
import uuid
import datetime
from streamlit_gsheets import GSheetsConnection

# -----------------------------------------------------------------------------
# Configuration & Setup
# -----------------------------------------------------------------------------
st.set_page_config(page_title="Trip Expense Manager", page_icon="💸", layout="centered")

MEMBERS = ["Getoar", "Arber", "Arbnor"]
CATEGORIES = ["Food", "Transport", "Housing", "Activities", "Other", "Settlement"]

conn = st.connection("gsheets", type=GSheetsConnection)

# --- Database Helper Functions ---
@st.cache_data(ttl=2)
def get_data():
    try:
        df = conn.read(worksheet="Expenses")
        df = df.dropna(how="all")
        
        numeric_cols = ["Total_Amount"] + [f"{m}_Paid" for m in MEMBERS]
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0.0)
                
        if "Linked_ID" not in df.columns:
            df["Linked_ID"] = ""
        else:
            df["Linked_ID"] = df["Linked_ID"].fillna("").astype(str)
            
        # FIX: Bulletproof parsing using Strings instead of Booleans
        if "Is_Active" not in df.columns:
            df["Is_Active"] = "Active"
        else:
            # If the cell says 'False', 'Archived', or '0', mark as Archived. Otherwise, Active.
            df["Is_Active"] = df["Is_Active"].apply(
                lambda x: "Archived" if "archiv" in str(x).lower() or str(x).strip().lower() in ['false', '0', 'no'] else "Active"
            )
            
        return df
    except Exception as e:
        st.error(f"Error reading from Google Sheets. Details: {e}")
        return pd.DataFrame()

def add_row(new_data_dict):
    df = get_data()
    new_df = pd.DataFrame([new_data_dict])
    updated_df = pd.concat([df, new_df], ignore_index=True)
    conn.update(worksheet="Expenses", data=updated_df)
    st.cache_data.clear()

def delete_row(row_id):
    df = get_data()
    updated_df = df[(df["ID"] != row_id) & (df["Linked_ID"] != row_id)]
    conn.update(worksheet="Expenses", data=updated_df)
    st.cache_data.clear()

def update_row(row_id, updated_data_dict):
    df = get_data()
    idx = df[df["ID"] == row_id].index
    if not idx.empty:
        for key, value in updated_data_dict.items():
            df.at[idx[0], key] = value
        conn.update(worksheet="Expenses", data=df)
        st.cache_data.clear()

def archive_all_active_rows():
    df = get_data()
    if not df.empty:
        df["Is_Active"] = "Archived" # Changed from False to "Archived"
        conn.update(worksheet="Expenses", data=df)
        st.cache_data.clear()

# --- Session States ---
if "active_form" not in st.session_state:
    st.session_state.active_form = None 
if "edit_id" not in st.session_state:
    st.session_state.edit_id = None
if "settle_id" not in st.session_state:
    st.session_state.settle_id = None

# -----------------------------------------------------------------------------
# App UI: Single Dashboard View
# -----------------------------------------------------------------------------
st.title("✈️ Trip Dashboard")

df = get_data()

# =============================================================================
# 1. Top Metrics & Balances (The Global Splitwise Math)
# =============================================================================
if not df.empty:
    trip_expenses = df[df["Category"] != "Settlement"]
    total_trip_cost = trip_expenses["Total_Amount"].sum()

    # Calculate Net Spent for each member: (Paid for Expenses) + (Sent Money) - (Received Money)
    member_spent = {m: 0.0 for m in MEMBERS}
    
    for idx, row in df.iterrows():
        if row["Category"] == "Settlement":
            receiver = row.get("Receiver")
            for m in MEMBERS:
                # Add what they sent
                member_spent[m] += row.get(f"{m}_Paid", 0.0)
                # Subtract what they received
                if m == receiver:
                    member_spent[m] -= row.get("Total_Amount", 0.0)
        else:
            # Standard expense: just add what they paid out of pocket
            for m in MEMBERS:
                member_spent[m] += row.get(f"{m}_Paid", 0.0)
    
    # Color palette for each member (Hex codes designed for dark mode)
    MEMBER_COLORS = {
        "Getoar": "#4facf7", # Light Blue
        "Arber": "#f7a94f",  # Orange
        "Arbnor": "#a74ff7"  # Purple
    }
    
    # Display Total Cost and individual spent amounts in a single row
    top_cols = st.columns(len(MEMBERS) + 1)
    
    # Total Cost remains a standard Streamlit metric
    top_cols[0].metric("Total Trip Cost", f"€{total_trip_cost:,.2f}")
    
    # Custom HTML metrics for colored member amounts
    for i, member in enumerate(MEMBERS):
        color = MEMBER_COLORS.get(member, "#ffffff")
        html_metric = f"""
        <div style="line-height: 1.2; font-family: sans-serif;">
            <div style="font-size: 0.875rem; color: #a3a8b8; margin-bottom: 0.25rem;">{member} Net Spent</div>
            <div style="font-size: 1.75rem; font-weight: 600; color: {color};">€{member_spent[member]:,.2f}</div>
        </div>
        """
        top_cols[i+1].markdown(html_metric, unsafe_allow_html=True)
        
    st.divider() 
    st.markdown("### ⚖️ Current Balances")
    
    balances = {m: 0.0 for m in MEMBERS}
    
    for idx, row in df.iterrows():
        total_amt = row.get("Total_Amount", 0.0)
        
        if row["Category"] == "Settlement":
            receiver = row.get("Receiver")
            for m in MEMBERS:
                balances[m] += row.get(f"{m}_Paid", 0.0) 
                if m == receiver:
                    balances[m] -= total_amt
        else:
            split = total_amt / len(MEMBERS)
            for m in MEMBERS:
                balances[m] += row.get(f"{m}_Paid", 0.0) - split

    st.caption("Positive (Green) means you are owed money. Negative (Red) means you owe money.")
    cols = st.columns(len(MEMBERS))
    for i, member in enumerate(MEMBERS):
        balance = round(balances[member], 2)

        # Format the minus sign to be at the very front so Streamlit recognizes it
        formatted_balance = f"€{balance:,.2f}" if balance >= 0 else f"-€{abs(balance):,.2f}"
        
        # Let Streamlit handle the default Green (positive) and Red (negative). 
        # Only turn it gray ("off") if the balance is zero.
        color = "normal" if abs(balance) > 0.01 else "off"
        
        cols[i].metric(member, formatted_balance, delta=formatted_balance, delta_color=color)

    st.write("")

    # =========================================================================
    # Settlement Plan & Matrix (Dropdown)
    # =========================================================================
    debtors = {m: -round(b, 2) for m, b in balances.items() if round(b, 2) < 0}
    creditors = {m: round(b, 2) for m, b in balances.items() if round(b, 2) > 0}
    settlements = []
    
    for debtor, debt in debtors.items():
        for creditor, credit in creditors.items():
            if debt <= 0.001: break
            if credit <= 0.001: continue
            amount = min(debt, credit)
            settlements.append((debtor, creditor, amount))
            debtors[debtor] -= amount
            creditors[creditor] -= amount
            debt -= amount
            
    if settlements:
        st.caption("Expand for more details.")
        with st.expander("💸 View Settlement Plan & Debt Matrix", expanded=False):
            st.markdown("**The simplest way to square up:**")
            
            # 1. Visual Directed List (Graph Alternative)
            for debtor, creditor, amount in settlements:
                st.error(f"**{debtor}** &nbsp; ➔ &nbsp; owes &nbsp; ➔ &nbsp; **{creditor}** &nbsp; : &nbsp; **€{amount:,.2f}**")
            
            st.divider()
            
            # 2. Detailed Matrix Table
            st.markdown("**Detailed Debt Matrix (All Combinations):**")
            matrix_df = pd.DataFrame(0.0, index=MEMBERS, columns=MEMBERS)
            
            for debtor, creditor, amount in settlements:
                matrix_df.at[debtor, creditor] = amount
                
            formatted_df = matrix_df.copy()
            for col in formatted_df.columns:
                formatted_df[col] = formatted_df[col].apply(lambda x: f"€{x:,.2f}" if x > 0 else "-")
                
            formatted_df.index.name = "Who Owes ▼"
            formatted_df.columns.name = "To Whom ►"
            
            st.table(formatted_df)
    else:
        st.success("🎉 Everyone is settled up! Nobody owes anything.")
        
        # AUTOMATIC ARCHIVING LOGIC
        # If the balances are zero, but there are still Active rows, archive them immediately and rerun!
        if (df["Is_Active"] == "Active").any():
            archive_all_active_rows()
            st.rerun()

st.divider()

# =============================================================================
# 2. Add New Expense Form (Top Level Buttons)
# =============================================================================
col_head, col_btn_exp, col_btn_set = st.columns([2, 1, 1])

with col_head:
    st.subheader("Expense Ledger")
    
with col_btn_exp:
    exp_label = "Cancel" if st.session_state.active_form == "Expense" else "➕ Add Expense"
    if st.button(exp_label, use_container_width=True, type="primary"):
        st.session_state.active_form = None if st.session_state.active_form == "Expense" else "Expense"
        st.session_state.edit_id = None 
        st.session_state.settle_id = None
        st.rerun()

with col_btn_set:
    # Uses default type to give it a distinct contrasting color
    set_label = "Cancel" if st.session_state.active_form == "Settlement" else "🤝 General Settlement"
    if st.button(set_label, use_container_width=True):
        st.session_state.active_form = None if st.session_state.active_form == "Settlement" else "Settlement"
        st.session_state.edit_id = None 
        st.session_state.settle_id = None
        st.rerun()

# Render Standard Expense Form
if st.session_state.active_form == "Expense":
    with st.container(border=True):
        st.markdown("### 🧾 Log a New Expense")
        with st.form("expense_form"):
            date = st.date_input("Date", datetime.date.today())
            c1, c2 = st.columns([2, 1])
            with c1: item = st.text_input("Item Description", placeholder="e.g., Nafti / Fuel")
            with c2: category = st.selectbox("Category", [c for c in CATEGORIES if c != "Settlement"])
            
            st.markdown("**Who paid and how much?**")
            paids = {}
            cols = st.columns(len(MEMBERS))
            for i, member in enumerate(MEMBERS):
                with cols[i]:
                    paids[member] = st.number_input(f"{member} Paid (€)", min_value=0.0, format="%.2f")

            submitted = st.form_submit_button("Add Expense", use_container_width=True)
            if submitted:
                total_amount = sum(paids.values())
                if not item or total_amount <= 0:
                    st.error("Please enter a description and ensure total > €0.")
                    st.stop()

                new_row = {
                    "ID": str(uuid.uuid4()),
                    "Date": date.strftime("%Y-%m-%d"),
                    "Item": item,
                    "Category": category,
                    "Receiver": "None", 
                    "Total_Amount": total_amount,
                    "Split_Type": "Equal",
                    "Linked_ID": "",
                    "Is_Active": "Active"  # Always active string
                }
                for member in MEMBERS:
                    new_row[f"{member}_Paid"] = paids[member]
                add_row(new_row)
                st.session_state.active_form = None
                st.rerun()

# Render General Settlement Form
elif st.session_state.active_form == "Settlement":
    with st.container(border=True):
        st.markdown("### 💸 Log a General Settlement")
        with st.form("repayment_form"):
            st.caption("Log a generic cash transfer between two people.")
            c1, c2 = st.columns(2)
            with c1: sender = st.selectbox("Who Sent Money?", MEMBERS)
            with c2: receiver = st.selectbox("Who Received Money?", reversed(MEMBERS))
            amount = st.number_input("Amount Sent (€)", min_value=0.01, format="%.2f")
            date = st.date_input("Date", datetime.date.today())
            
            submitted = st.form_submit_button("Log Payment", use_container_width=True)
            if submitted:
                if sender == receiver:
                    st.error("Cannot send to self.")
                    st.stop()
                new_row = {
                    "ID": str(uuid.uuid4()),
                    "Date": date.strftime("%Y-%m-%d"),
                    "Item": "General Repayment",
                    "Category": "Settlement",
                    "Receiver": receiver, 
                    "Total_Amount": amount,
                    "Split_Type": "Repayment",
                    "Linked_ID": "",
                    "Is_Active": "Active" # Always active string
                }
                for member in MEMBERS:
                    new_row[f"{member}_Paid"] = amount if member == sender else 0.0
                add_row(new_row)
                st.session_state.active_form = None
                st.rerun()
                
st.write("") 

# =============================================================================
# 3. Ledger Feed (Grouped view)
# =============================================================================
if df.empty:
    st.info("No expenses logged yet. Use the buttons above to get started!")
else:
    main_feed = df[df["Linked_ID"] == ""].copy()
    display_df = main_feed.iloc[::-1] 
    
    for idx, row in display_df.iterrows():
        exp_id = row["ID"]
        # Determine Activity based on the string word
        is_active = (row.get("Is_Active", "Active") == "Active")
        
        with st.container(border=True):
            
            icon = "💸" if row["Category"] == "Settlement" else "🧾"
            st.markdown(f"**{icon} {row['Date']} | {row['Item']} | €{row['Total_Amount']:.2f}**")
            
            if row["Category"] == "Settlement":
                sender = next((m for m in MEMBERS if row.get(f"{m}_Paid", 0.0) > 0), "Unknown")
                receiver = row.get("Receiver", "Unknown")
                st.markdown(f"**Repayment:** {sender} paid {receiver}")
                if not is_active:
                    st.caption("🔒 _Archived_")
                
            else:
                split_amt = row['Total_Amount'] / len(MEMBERS)
                payers = {m: row.get(f"{m}_Paid", 0.0) for m in MEMBERS}
                paid_list = [f"{m}: €{amt:.2f}" for m, amt in payers.items() if amt > 0]
                primary_receiver = max(payers, key=payers.get) 
                
                st.markdown(f"**Paid by:** " + " • ".join(paid_list))
                
                linked_settlements = df[df["Linked_ID"] == exp_id]
                
                if not linked_settlements.empty:
                    st.markdown("---")
                    st.markdown("**🔄 Linked Settlements:**")
                    for _, s_row in linked_settlements.iterrows():
                        s_sender = next((m for m in MEMBERS if s_row.get(f"{m}_Paid", 0.0) > 0), "Unknown")
                        s_receiver = s_row.get("Receiver", "Unknown")
                        st.caption(f"↳ {s_sender} settled **€{s_row['Total_Amount']:.2f}** with {s_receiver}")

                receipt_balances = {m: payers[m] - split_amt for m in MEMBERS}
                for _, s_row in linked_settlements.iterrows():
                    s_sender = next((m for m in MEMBERS if s_row.get(f"{m}_Paid", 0.0) > 0), None)
                    s_receiver = s_row.get("Receiver", None)
                    if s_sender and s_receiver:
                        receipt_balances[s_sender] += s_row['Total_Amount']
                        receipt_balances[s_receiver] -= s_row['Total_Amount']
                
                is_settled = all(round(b, 2) >= -0.01 for b in receipt_balances.values())

                if is_settled:
                    st.success("✅ **Expense is completely settled!**")
                elif not is_active:
                    st.caption("🔒 _Locked (Past Settlement)_")
                else:
                    st.caption(f"_Split 3 ways: €{split_amt:.2f} per person_")

            # --- INLINE SETTLE FORM ---
            if st.session_state.settle_id == exp_id:
                st.divider()
                with st.form(key=f"settle_form_{exp_id}"):
                    st.markdown(f"**Settle up for: {row['Item']}**")
                    
                    default_sender = min(receipt_balances, key=receipt_balances.get) if row["Category"] != "Settlement" else MEMBERS[0]
                    
                    c1, c2 = st.columns(2)
                    with c1: sender = st.selectbox("Who is paying?", MEMBERS, index=MEMBERS.index(default_sender))
                    with c2: receiver = st.selectbox("Who are they paying?", MEMBERS, index=MEMBERS.index(primary_receiver))
                    
                    default_amt = abs(receipt_balances[default_sender]) if receipt_balances.get(default_sender, 0) < 0 else 0.01
                    amount = st.number_input("Amount (€)", value=round(default_amt, 2), min_value=0.01)
                    
                    c_sub, c_can = st.columns(2)
                    if c_sub.form_submit_button("Submit Repayment", use_container_width=True):
                        new_row = {
                            "ID": str(uuid.uuid4()),
                            "Date": datetime.date.today().strftime("%Y-%m-%d"),
                            "Item": f"Settlement for {row['Item']}",
                            "Category": "Settlement",
                            "Receiver": receiver, 
                            "Total_Amount": amount,
                            "Split_Type": "Repayment",
                            "Linked_ID": exp_id,
                            "Is_Active": "Active"
                        }
                        for member in MEMBERS:
                            new_row[f"{member}_Paid"] = amount if member == sender else 0.0
                        add_row(new_row)
                        st.session_state.settle_id = None
                        st.rerun()
                    if c_can.form_submit_button("Cancel", use_container_width=True):
                        st.session_state.settle_id = None
                        st.rerun()

            # --- CARD ACTION BUTTONS ---
            elif st.session_state.edit_id != exp_id:
                cols_btns = st.columns([1.5, 1, 1, 3]) 
                
                # Only show Settle button if the expense is NOT globally archived and NOT individually settled
                if row["Category"] != "Settlement" and not is_settled and is_active:
                    if cols_btns[0].button("🤝 Settle", key=f"btn_settle_{exp_id}", use_container_width=True):
                        st.session_state.settle_id = exp_id
                        st.session_state.edit_id = None
                        st.session_state.active_form = None
                        st.rerun()
                        
                if cols_btns[1].button("✏️ Edit", key=f"edit_{exp_id}", use_container_width=True, disabled=not is_active):
                    st.session_state.edit_id = exp_id
                    st.session_state.settle_id = None
                    st.session_state.active_form = None
                    st.rerun()
                    
                if cols_btns[2].button("🗑️ Delete", key=f"del_{exp_id}", use_container_width=True, disabled=not is_active):
                    delete_row(exp_id)
                    st.rerun()

            # --- INLINE EDIT FORM ---
            if st.session_state.edit_id == exp_id:
                st.divider()
                with st.form(key=f"edit_form_{exp_id}"):
                    if row["Category"] == "Settlement":
                        st.markdown("**Edit Repayment**")
                        new_amount = st.number_input("Amount Sent (€)", value=float(row["Total_Amount"]), min_value=0.01)
                    else:
                        st.markdown("**Edit Expense**")
                        new_item = st.text_input("Item Description", value=row["Item"])
                        st.markdown("**Who paid and how much?**")
                        new_paids = {}
                        cols = st.columns(len(MEMBERS))
                        for i, m in enumerate(MEMBERS):
                            new_paids[m] = cols[i].number_input(f"{m} Paid (€)", value=float(row.get(f"{m}_Paid", 0.0)), min_value=0.0)

                    c_sub, c_can = st.columns(2)
                    save = c_sub.form_submit_button("Save Changes", use_container_width=True)
                    cancel = c_can.form_submit_button("Cancel", use_container_width=True)
                    
                    if save:
                        if row["Category"] == "Settlement":
                            sender = next((m for m in MEMBERS if row.get(f"{m}_Paid", 0.0) > 0), MEMBERS[0])
                            updated_data = {"Total_Amount": new_amount}
                            for m in MEMBERS:
                                updated_data[f"{m}_Paid"] = new_amount if m == sender else 0.0
                        else:
                            updated_data = {
                                "Item": new_item,
                                "Total_Amount": sum(new_paids.values()),
                            }
                            for m in MEMBERS:
                                updated_data[f"{m}_Paid"] = new_paids[m]
                                
                        update_row(exp_id, updated_data)
                        st.session_state.edit_id = None
                        st.rerun()
                        
                    if cancel:
                        st.session_state.edit_id = None
                        st.rerun()
