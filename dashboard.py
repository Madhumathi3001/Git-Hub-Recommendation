import streamlit as st
from pymongo import MongoClient
import pandas as pd
import matplotlib.pyplot as plt
from wordcloud import WordCloud
import plotly.express as px
import plotly.graph_objects as go
import requests
import os
from datetime import datetime, timezone
from dateutil import parser
from dotenv import load_dotenv

# Load environment variables
load_dotenv(dotenv_path='password.env')
GITHUB_API_KEY = os.getenv("GITHUB_API_KEY")
MONGO_URI = os.getenv("MONGO_URI")

# MongoDB setup
client = MongoClient(MONGO_URI)
db = client["github_db"]
collection = db["user_data"]

# Helper function: fetch commit count
def get_commit_count(username, repo_name, headers):
    url = f"https://api.github.com/repos/{username}/{repo_name}/commits?per_page=1"
    resp = requests.get(url, headers=headers)
    if resp.status_code != 200:
        return 0
    if 'Link' in resp.headers:
        links = resp.headers['Link']
        last_links = [link for link in links.split(',') if 'rel="last"' in link]
        if last_links:
            last_url = last_links[0].split(';')[0].strip('<> ')
            try:
                total_commits = int(last_url.split('page=')[-1])
                return total_commits
            except:
                return 0
    return len(resp.json())

# Fetch user data from GitHub API
def fetch_user_data(username):
    headers = {"Authorization": f"token {GITHUB_API_KEY}"} if GITHUB_API_KEY else {}
    user_url = f"https://api.github.com/users/{username}"
    repos_url = f"https://api.github.com/users/{username}/repos?per_page=100"
    starred_url = f"https://api.github.com/users/{username}/starred?per_page=100"

    user_resp = requests.get(user_url, headers=headers)
    if user_resp.status_code != 200:
        return None
    user_json = user_resp.json()

    repos_resp = requests.get(repos_url, headers=headers)
    repos = repos_resp.json() if repos_resp.status_code == 200 else []

    starred_resp = requests.get(starred_url, headers=headers)
    starred = starred_resp.json() if starred_resp.status_code == 200 else []

    languages, commits_per_repo, stars_per_repo, stars_per_language, commits_per_language = {}, {}, {}, {}, {}
    commit_dates = []

    for repo in repos:
        lang = repo.get("language") or "Unknown"
        repo_name = repo.get("name") or "Unknown"
        stars = repo.get("stargazers_count") or 0
        size = repo.get("size") or 0

        languages[lang] = languages.get(lang, 0) + size
        stars_per_language[lang] = stars_per_language.get(lang, 0) + stars
        stars_per_repo[repo_name] = stars

        commits_count = get_commit_count(username, repo_name, headers)
        commits_per_repo[repo_name] = commits_count

        commits_url = f"https://api.github.com/repos/{username}/{repo_name}/commits?per_page=100"
        commits_resp = requests.get(commits_url, headers=headers)
        if commits_resp.status_code == 200:
            for commit in commits_resp.json():
                date_str = commit.get("commit", {}).get("author", {}).get("date")
                if date_str:
                    commit_dates.append(parser.isoparse(date_str))

    for lang in languages.keys():
        commits_per_language[lang] = sum(
            commits_per_repo.get(repo.get("name") or "", 0) 
            for repo in repos if (repo.get("language") or "Unknown") == lang
        )

    return {
        "Login": username,
        "Name": user_json.get("name") or username,
        "Avatar URL": user_json.get("avatar_url"),
        "Profile URL": user_json.get("html_url"),
        "Bio": user_json.get("bio") or "",
        "Created At": user_json.get("created_at"),
        "Followers Count": user_json.get("followers") or 0,
        "Following Count": user_json.get("following") or 0,
        "Public Repositories": user_json.get("public_repos") or 0,
        "Languages": languages,
        "Commits Per Repo": commits_per_repo,
        "Stars Per Repo": stars_per_repo,
        "Stars Per Language": stars_per_language,
        "Commits Per Language": commits_per_language,
        "Starred Repositories": [repo.get("html_url") for repo in starred],
        "Commit Dates": commit_dates,
        "Platforms": ["Linux", "Windows", "macOS"],
        "Web Frameworks": {"Django": 3, "Flask": 2, "React": 5},
        "Total Commits": sum(commits_per_repo.values())
    }

# Streamlit UI
st.set_page_config(page_title="GitHub User Analytics", layout="wide")
st.title("🚀 GitHub User Analytics Dashboard")

username = st.sidebar.text_input("Enter GitHub Username:")

if username:
    user = collection.find_one({"Login": username})
    if not user:
        st.info(f"Fetching data for {username}...")
        user = fetch_user_data(username)
        if user:
            collection.insert_one(user)
        else:
            st.error("User not found or API limit reached.")
            st.stop()

    st.subheader(f"👤 {user.get('Name', 'Unknown')} (@{user['Login']})")
    st.image(user.get("Avatar URL", ""), width=150)
    st.markdown(f"[GitHub Profile]({user.get('Profile URL', '')})")
    created_at = parser.isoparse(user.get("Created At")) if isinstance(user.get("Created At"), str) else user.get("Created At")
    if created_at:
        now = datetime.now(timezone.utc)
        duration = now - created_at
        years, remainder = divmod(duration.days, 365)
        months = remainder // 30
        st.write(f"**Joined:** {years} years and {months} months ago")
    else:
        st.write("**Joined:** Unknown")
    st.write(f"**Followers:** {user.get('Followers Count', 0)} | **Following:** {user.get('Following Count', 0)} | **Public Repos:** {user.get('Public Repositories', 0)}")

    # Pie chart helper (no labels, only legend)
    def plot_pie_chart(data_dict, title):
        df = pd.DataFrame(list(data_dict.items()), columns=["Label", "Value"]) if data_dict else pd.DataFrame([["None", 1]], columns=["Label", "Value"])
        fig = px.pie(df, names="Label", values="Value", hole=0.4, title=title)
        fig.update_traces(textinfo='none')  # Remove labels from inside
        st.plotly_chart(fig, use_container_width=True)

    st.subheader("🍩 Donut Charts")
    plot_pie_chart(user.get("Languages", {}), "Repos per Language (by size)")
    plot_pie_chart(user.get("Stars Per Language", {}), "Stars per Language")
    plot_pie_chart(user.get("Commits Per Language", {}), "Commits per Language")
    plot_pie_chart(user.get("Stars Per Repo", {}), "Stars per Repo")
    plot_pie_chart(user.get("Commits Per Repo", {}), "Commits per Repo")

    # Line chart for commits per quarter
    st.subheader("📈 Commits per Quarter")
    commit_dates = user.get("Commit Dates", [])
    if commit_dates:
        df = pd.DataFrame({"Date": commit_dates})
        df['Quarter'] = df['Date'].dt.to_period('Q').astype(str)
        commits_per_quarter = df.groupby('Quarter').size().reset_index(name='Commits')
        fig_line = px.line(commits_per_quarter, x='Quarter', y='Commits', markers=True, title="Commits per Quarter")
        st.plotly_chart(fig_line, use_container_width=True)
    else:
        st.info("No commit date data available.")

    # WordCloud for platforms
    st.subheader("☁️ Platforms Used")
    platforms = user.get("Platforms", [])
    wc = WordCloud(width=800, height=400, background_color="white").generate(" ".join(platforms))
    fig_wc, ax_wc = plt.subplots(figsize=(10, 5))
    ax_wc.imshow(wc, interpolation="bilinear")
    ax_wc.axis("off")
    st.pyplot(fig_wc)

    # Packed bubble chart for frameworks
    st.subheader("🌐 Web Frameworks")
    frameworks = user.get("Web Frameworks", {"None": 1})
    labels, values = zip(*frameworks.items())
    sizes = [max(20, (v / max(values)) * 100) for v in values]
    fig_bubble = go.Figure()
    fig_bubble.add_trace(go.Scatter(
        x=[0]*len(labels), y=[0]*len(labels), mode='markers+text',
        marker=dict(size=sizes, color=values, colorscale='Viridis', showscale=True, line=dict(width=2, color='DarkSlateGrey')),
        text=labels, textposition='middle center', hovertext=[f"{label}: {val}" for label, val in frameworks.items()],
        hoverinfo='text'
    ))
    fig_bubble.update_layout(
        title="Web Frameworks Usage", showlegend=False,
        xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
        yaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
        height=600
    )
    st.plotly_chart(fig_bubble, use_container_width=True)




