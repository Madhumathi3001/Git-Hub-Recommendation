import streamlit as st
import pandas as pd
from pymongo import MongoClient
import requests
import time
from sklearn.preprocessing import MultiLabelBinarizer
from sklearn.metrics.pairwise import cosine_similarity
import numpy as np
from dotenv import load_dotenv
import os

load_dotenv(dotenv_path='password.env')

# === Environment Variables ===
GITHUB_API_KEY = os.getenv("GITHUB_API_KEY")
MONGO_URI = os.getenv("MONGO_URI")

# === MongoDB Setup ===
client = MongoClient(MONGO_URI)  # Use the env variable here!
db = client["github_db"]
collection = db["user_data"]

# === GitHub API Setup ===
HEADERS = {
    "Authorization": f"token {GITHUB_API_KEY}",
    "Accept": "application/vnd.github.v3+json"
}

# === GitHub API Helper Functions ===
def get_json(url):
    response = requests.get(url, headers=HEADERS)
    if response.status_code == 403:  # Rate limit handling
        with st.spinner("Rate limit reached, waiting 60 seconds... ⏳"):
            time.sleep(60)
            response = requests.get(url, headers=HEADERS)
    response.raise_for_status()
    return response.json()

def get_list(url, key='login'):
    try:
        return [item[key] for item in get_json(url)]
    except Exception:
        return []

def get_starred_or_subs(url):
    try:
        return [item['html_url'] for item in get_json(url)]
    except Exception:
        return []

def get_languages(username):
    try:
        repos = get_json(f"https://api.github.com/users/{username}/repos")
        language_data = {}
        for repo in repos:
            langs = get_json(repo['languages_url'])
            for lang, count in langs.items():
                language_data[lang] = language_data.get(lang, 0) + count
        return language_data
    except Exception:
        return {}

def get_total_commits(username):
    try:
        repos = get_json(f"https://api.github.com/users/{username}/repos")
        total = 0
        for repo in repos:
            if repo.get('fork'):
                continue
            commits_url = repo['commits_url'].replace("{/sha}", "")
            commits_resp = requests.get(commits_url, headers=HEADERS, params={'per_page': 1})
            if commits_resp.status_code == 200:
                commits = commits_resp.json()
                if isinstance(commits, list):
                    total += len(commits)
        return total
    except Exception:
        return 0

def fetch_and_store_user(username):
    try:
        with st.spinner(f"Fetching data for user '{username}'... 🔍"):
            user = get_json(f"https://api.github.com/users/{username}")
            data = {
                "Login": user.get("login"),
                "Name": user.get("name"),
                "Bio": user.get("bio"),
                "Public Repositories": user.get("public_repos"),
                "Followers Count": user.get("followers"),
                "Following Count": user.get("following"),
                "Created At": user.get("created_at"),
                "Updated At": user.get("updated_at"),
                "Avatar URL": user.get("avatar_url"),
                "Profile URL": user.get("html_url"),
                "Followers List": get_list(user.get("followers_url")),
                "Following List": get_list(user.get("following_url").split("{")[0]),
                "Starred Repositories": get_starred_or_subs(f"https://api.github.com/users/{username}/starred"),
                "Subscriptions": get_starred_or_subs(f"https://api.github.com/users/{username}/subscriptions"),
                "Organizations": get_list(f"https://api.github.com/users/{username}/orgs"),
                "Languages": get_languages(username),
                "Total Commits": get_total_commits(username)
            }
            collection.update_one({"Login": username}, {"$set": data}, upsert=True)
            return data
    except Exception as e:
        st.error(f"Failed to fetch user data for {username}: {e}")
        return None

# === Data Preprocessing ===
def preprocess_languages(df):
    df['LanguagesList'] = df['Languages'].apply(lambda x: list(x.keys()) if isinstance(x, dict) else [])
    df_nonempty = df[df['LanguagesList'].map(len) > 0].reset_index(drop=True)
    return df_nonempty

# === Recommendation Function ===
def get_recommendations(df, username, top_n=10):
    if username not in df['Login'].values:
        return None

    mlb = MultiLabelBinarizer()
    lang_matrix = mlb.fit_transform(df['LanguagesList'])

    similarity = cosine_similarity(lang_matrix)
    user_idx = df.index[df['Login'] == username][0]
    sim_scores = list(enumerate(similarity[user_idx]))
    sim_scores = [(idx, score) for idx, score in sim_scores if idx != user_idx]
    sim_scores = sorted(sim_scores, key=lambda x: x[1], reverse=True)[:top_n]

    recommendations = []
    user_langs = set(df.at[user_idx, 'LanguagesList'])

    for idx, score in sim_scores:
        rec_user = df.iloc[idx]
        rec_langs = set(rec_user['LanguagesList'])
        common_langs = user_langs.intersection(rec_langs)
        recommendations.append({
            "Login": rec_user['Login'],
            "Profile URL": rec_user['Profile URL'],
            "Common Languages": ", ".join(common_langs),
            "Similarity Score": round(score, 3),
            "Avatar": rec_user['Avatar URL']
        })
    return recommendations

# === Load Data from DB ===
def load_data():
    data = list(collection.find())
    if not data:
        return pd.DataFrame()
    df = pd.DataFrame(data)
    df = preprocess_languages(df)
    return df

# === Streamlit App ===
st.set_page_config(page_title="GitHub User Recommendation", layout="wide", page_icon="🐙")

st.markdown("""
    <h1 style='text-align:center; color:#6f42c1;'>🐙 GitHub User Recommendation System</h1>
    <p style='text-align:center; font-size:18px; color:#555;'>Find GitHub users with similar programming language interests</p>
""", unsafe_allow_html=True)

df = load_data()

username = st.text_input("Enter GitHub Username to get recommendations:", placeholder="e.g., torvalds")

if st.button("Get Recommendations"):

    if not username:
        st.warning("⚠️ Please enter a GitHub username!")
    else:
        if username not in df['Login'].values:
            st.info(f"User '{username}' not found in database. Fetching live from GitHub API...")
            new_user = fetch_and_store_user(username)
            if new_user:
                df = load_data()
            else:
                st.stop()

        recommendations = get_recommendations(df, username)
        if not recommendations:
            st.warning("No recommendations found or user does not exist.")
        else:
            st.subheader(f"Top 10 GitHub users similar to '{username}':")

            # Display the main user info nicely
            main_user = df[df['Login'] == username].iloc[0]
            with st.container():
                col1, col2 = st.columns([1,4])
                with col1:
                    st.image(main_user['Avatar URL'], width=100)
                with col2:
                    st.markdown(f"### [{main_user['Login']}]({main_user['Profile URL']})")
                    if main_user['Name']:
                        st.markdown(f"**Name:** {main_user['Name']}")
                    if main_user['Bio']:
                        st.markdown(f"_{main_user['Bio']}_")
                    st.markdown(f"**Public Repos:** {main_user['Public Repositories']} | **Followers:** {main_user['Followers Count']}")

            st.markdown("---")

            # Recommendations as cards
            for rec in recommendations:
                with st.container():
                    cols = st.columns([1,4,2,1])
                    cols[0].image(rec['Avatar'], width=60)
                    cols[1].markdown(f"### [{rec['Login']}]({rec['Profile URL']})")
                    cols[2].markdown(f"**Common Languages:** {rec['Common Languages']}")
                    cols[3].markdown(f"**Score:** {rec['Similarity Score']}")
                    st.markdown("---")

# Footer
st.markdown(
    """
    <style>
    footer {visibility: hidden;}
    </style>
    """, unsafe_allow_html=True
)






