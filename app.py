from flask import Flask, render_template, request, redirect, url_for, flash, session
import sqlite3
from datetime import datetime
from functools import wraps

app = Flask(__name__)
app.secret_key = "advanced-cricket-app-secret"
DB_NAME = "cricket_v2.db"


def get_db():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


def balls_to_overs(balls):
    balls = balls or 0
    return f"{balls // 6}.{balls % 6}"


@app.context_processor
def inject_helpers():
    return dict(balls_to_overs=balls_to_overs)


def init_db():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS teams (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL,
        captain TEXT,
        city TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS players (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        role TEXT,
        team_id INTEGER NOT NULL,
        FOREIGN KEY(team_id) REFERENCES teams(id)
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS matches (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        team1_id INTEGER NOT NULL,
        team2_id INTEGER NOT NULL,
        toss_winner_id INTEGER,
        first_batting_team_id INTEGER NOT NULL,
        second_batting_team_id INTEGER NOT NULL,
        total_overs INTEGER DEFAULT 5,
        status TEXT DEFAULT 'LIVE',
        current_innings INTEGER DEFAULT 1,
        winner_team_id INTEGER,
        result_text TEXT,
        created_at TEXT,
        FOREIGN KEY(team1_id) REFERENCES teams(id),
        FOREIGN KEY(team2_id) REFERENCES teams(id),
        FOREIGN KEY(toss_winner_id) REFERENCES teams(id),
        FOREIGN KEY(first_batting_team_id) REFERENCES teams(id),
        FOREIGN KEY(second_batting_team_id) REFERENCES teams(id),
        FOREIGN KEY(winner_team_id) REFERENCES teams(id)
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS innings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        match_id INTEGER NOT NULL,
        innings_no INTEGER NOT NULL,
        batting_team_id INTEGER NOT NULL,
        bowling_team_id INTEGER NOT NULL,
        runs INTEGER DEFAULT 0,
        wickets INTEGER DEFAULT 0,
        balls INTEGER DEFAULT 0,
        status TEXT DEFAULT 'LIVE',
        FOREIGN KEY(match_id) REFERENCES matches(id),
        FOREIGN KEY(batting_team_id) REFERENCES teams(id),
        FOREIGN KEY(bowling_team_id) REFERENCES teams(id)
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS balls (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        match_id INTEGER NOT NULL,
        innings_id INTEGER NOT NULL,
        innings_no INTEGER NOT NULL,
        over_no INTEGER,
        ball_no INTEGER,
        batsman_id INTEGER,
        bowler_id INTEGER,
        runs INTEGER DEFAULT 0,
        extra_type TEXT,
        extra_runs INTEGER DEFAULT 0,
        is_wicket INTEGER DEFAULT 0,
        wicket_player_id INTEGER,
        note TEXT,
        created_at TEXT,
        FOREIGN KEY(match_id) REFERENCES matches(id),
        FOREIGN KEY(innings_id) REFERENCES innings(id),
        FOREIGN KEY(batsman_id) REFERENCES players(id),
        FOREIGN KEY(bowler_id) REFERENCES players(id),
        FOREIGN KEY(wicket_player_id) REFERENCES players(id)
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS batting_stats (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        match_id INTEGER NOT NULL,
        innings_id INTEGER NOT NULL,
        player_id INTEGER NOT NULL,
        runs INTEGER DEFAULT 0,
        balls INTEGER DEFAULT 0,
        fours INTEGER DEFAULT 0,
        sixes INTEGER DEFAULT 0,
        out_status TEXT DEFAULT 'Not Out',
        UNIQUE(match_id, innings_id, player_id)
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS bowling_stats (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        match_id INTEGER NOT NULL,
        innings_id INTEGER NOT NULL,
        player_id INTEGER NOT NULL,
        runs_given INTEGER DEFAULT 0,
        balls INTEGER DEFAULT 0,
        wickets INTEGER DEFAULT 0,
        UNIQUE(match_id, innings_id, player_id)
    )
    """)

    cur.execute("INSERT OR IGNORE INTO users (username, password) VALUES ('admin', 'admin123')")

    conn.commit()
    conn.close()


def login_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return func(*args, **kwargs)
    return wrapper


def row_count(conn, table):
    return conn.execute(f"SELECT COUNT(*) AS c FROM {table}").fetchone()["c"]


def get_match(conn, match_id):
    return conn.execute("""
        SELECT m.*,
               t1.name AS team1_name,
               t2.name AS team2_name,
               toss.name AS toss_winner_name,
               fb.name AS first_batting_name,
               sb.name AS second_batting_name,
               wt.name AS winner_name
        FROM matches m
        JOIN teams t1 ON m.team1_id = t1.id
        JOIN teams t2 ON m.team2_id = t2.id
        LEFT JOIN teams toss ON m.toss_winner_id = toss.id
        JOIN teams fb ON m.first_batting_team_id = fb.id
        JOIN teams sb ON m.second_batting_team_id = sb.id
        LEFT JOIN teams wt ON m.winner_team_id = wt.id
        WHERE m.id = ?
    """, (match_id,)).fetchone()


def get_current_innings(conn, match_id):
    match = conn.execute("SELECT current_innings FROM matches WHERE id = ?", (match_id,)).fetchone()
    if not match:
        return None
    return conn.execute("""
        SELECT inn.*,
               bt.name AS batting_team_name,
               bw.name AS bowling_team_name
        FROM innings inn
        JOIN teams bt ON inn.batting_team_id = bt.id
        JOIN teams bw ON inn.bowling_team_id = bw.id
        WHERE inn.match_id = ? AND inn.innings_no = ?
    """, (match_id, match["current_innings"])).fetchone()


def ensure_batting_stat(conn, match_id, innings_id, player_id):
    conn.execute("""
        INSERT OR IGNORE INTO batting_stats (match_id, innings_id, player_id)
        VALUES (?, ?, ?)
    """, (match_id, innings_id, player_id))


def ensure_bowling_stat(conn, match_id, innings_id, player_id):
    conn.execute("""
        INSERT OR IGNORE INTO bowling_stats (match_id, innings_id, player_id)
        VALUES (?, ?, ?)
    """, (match_id, innings_id, player_id))


def complete_match_if_needed(conn, match_id):
    match = get_match(conn, match_id)
    innings1 = conn.execute("SELECT * FROM innings WHERE match_id=? AND innings_no=1", (match_id,)).fetchone()
    innings2 = conn.execute("SELECT * FROM innings WHERE match_id=? AND innings_no=2", (match_id,)).fetchone()

    if not innings1 or not innings2:
        return

    if innings2["status"] == "COMPLETED":
        if innings2["runs"] > innings1["runs"]:
            winner_id = innings2["batting_team_id"]
            result = f"{match['second_batting_name']} won by {10 - innings2['wickets']} wickets"
        elif innings1["runs"] > innings2["runs"]:
            winner_id = innings1["batting_team_id"]
            result = f"{match['first_batting_name']} won by {innings1['runs'] - innings2['runs']} runs"
        else:
            winner_id = None
            result = "Match tied"

        conn.execute("""
            UPDATE matches
            SET status='COMPLETED', winner_team_id=?, result_text=?
            WHERE id=?
        """, (winner_id, result, match_id))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        conn = get_db()
        user = conn.execute(
            "SELECT * FROM users WHERE username=? AND password=?",
            (username, password)
        ).fetchone()
        conn.close()

        if user:
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            return redirect(url_for("index"))
        flash("Wrong username or password.")

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
@login_required
def index():
    conn = get_db()
    teams_count = row_count(conn, "teams")
    players_count = row_count(conn, "players")
    matches_count = row_count(conn, "matches")
    completed_count = conn.execute("SELECT COUNT(*) AS c FROM matches WHERE status='COMPLETED'").fetchone()["c"]

    live_matches = conn.execute("""
        SELECT m.*,
               t1.name AS team1_name,
               t2.name AS team2_name,
               fb.name AS first_batting_name,
               sb.name AS second_batting_name
        FROM matches m
        JOIN teams t1 ON m.team1_id = t1.id
        JOIN teams t2 ON m.team2_id = t2.id
        JOIN teams fb ON m.first_batting_team_id = fb.id
        JOIN teams sb ON m.second_batting_team_id = sb.id
        WHERE m.status='LIVE'
        ORDER BY m.id DESC
    """).fetchall()
    conn.close()

    return render_template(
        "index.html",
        teams_count=teams_count,
        players_count=players_count,
        matches_count=matches_count,
        completed_count=completed_count,
        live_matches=live_matches
    )


@app.route("/teams", methods=["GET", "POST"])
@login_required
def teams():
    conn = get_db()
    if request.method == "POST":
        try:
            conn.execute(
                "INSERT INTO teams (name, captain, city) VALUES (?, ?, ?)",
                (request.form["name"].strip(), request.form["captain"].strip(), request.form["city"].strip())
            )
            conn.commit()
            flash("Team added.")
        except sqlite3.IntegrityError:
            flash("Team name already exists.")
        return redirect(url_for("teams"))

    teams_data = conn.execute("SELECT * FROM teams ORDER BY id DESC").fetchall()
    conn.close()
    return render_template("teams.html", teams=teams_data)


@app.route("/delete-team/<int:team_id>", methods=["POST"])
@login_required
def delete_team(team_id):
    conn = get_db()
    used = conn.execute("""
        SELECT COUNT(*) AS c FROM matches WHERE team1_id=? OR team2_id=?
    """, (team_id, team_id)).fetchone()["c"]
    if used:
        flash("Cannot delete team used in matches.")
    else:
        conn.execute("DELETE FROM players WHERE team_id=?", (team_id,))
        conn.execute("DELETE FROM teams WHERE id=?", (team_id,))
        conn.commit()
        flash("Team deleted.")
    conn.close()
    return redirect(url_for("teams"))


@app.route("/players", methods=["GET", "POST"])
@login_required
def players():
    conn = get_db()
    teams_data = conn.execute("SELECT * FROM teams ORDER BY name").fetchall()

    if request.method == "POST":
        conn.execute(
            "INSERT INTO players (name, role, team_id) VALUES (?, ?, ?)",
            (request.form["name"].strip(), request.form["role"], request.form["team_id"])
        )
        conn.commit()
        flash("Player added.")
        return redirect(url_for("players"))

    players_data = conn.execute("""
        SELECT p.*, t.name AS team_name
        FROM players p
        JOIN teams t ON p.team_id=t.id
        ORDER BY t.name, p.name
    """).fetchall()
    conn.close()
    return render_template("players.html", players=players_data, teams=teams_data)


@app.route("/delete-player/<int:player_id>", methods=["POST"])
@login_required
def delete_player(player_id):
    conn = get_db()
    used = conn.execute("""
        SELECT COUNT(*) AS c FROM balls
        WHERE batsman_id=? OR bowler_id=? OR wicket_player_id=?
    """, (player_id, player_id, player_id)).fetchone()["c"]
    if used:
        flash("Cannot delete player used in scoring.")
    else:
        conn.execute("DELETE FROM players WHERE id=?", (player_id,))
        conn.commit()
        flash("Player deleted.")
    conn.close()
    return redirect(url_for("players"))


@app.route("/matches", methods=["GET", "POST"])
@login_required
def matches():
    conn = get_db()
    teams_data = conn.execute("SELECT * FROM teams ORDER BY name").fetchall()

    if request.method == "POST":
        team1_id = int(request.form["team1_id"])
        team2_id = int(request.form["team2_id"])
        toss_winner_id = int(request.form["toss_winner_id"])
        first_batting_team_id = int(request.form["first_batting_team_id"])
        total_overs = int(request.form["total_overs"])

        if team1_id == team2_id:
            flash("Both teams cannot be same.")
            return redirect(url_for("matches"))

        if first_batting_team_id not in [team1_id, team2_id]:
            flash("Batting team must be one of selected teams.")
            return redirect(url_for("matches"))

        second_batting_team_id = team2_id if first_batting_team_id == team1_id else team1_id

        cur = conn.cursor()
        cur.execute("""
            INSERT INTO matches (
                team1_id, team2_id, toss_winner_id, first_batting_team_id,
                second_batting_team_id, total_overs, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            team1_id, team2_id, toss_winner_id, first_batting_team_id,
            second_batting_team_id, total_overs,
            datetime.now().strftime("%Y-%m-%d %H:%M")
        ))
        match_id = cur.lastrowid

        conn.execute("""
            INSERT INTO innings (
                match_id, innings_no, batting_team_id, bowling_team_id
            )
            VALUES (?, 1, ?, ?)
        """, (match_id, first_batting_team_id, second_batting_team_id))

        conn.commit()
        flash("Match created.")
        return redirect(url_for("score", match_id=match_id))

    matches_data = conn.execute("""
        SELECT m.*,
               t1.name AS team1_name,
               t2.name AS team2_name,
               wt.name AS winner_name
        FROM matches m
        JOIN teams t1 ON m.team1_id=t1.id
        JOIN teams t2 ON m.team2_id=t2.id
        LEFT JOIN teams wt ON m.winner_team_id=wt.id
        ORDER BY m.id DESC
    """).fetchall()
    conn.close()
    return render_template("matches.html", teams=teams_data, matches=matches_data)


@app.route("/score/<int:match_id>", methods=["GET", "POST"])
@login_required
def score(match_id):
    conn = get_db()
    match = get_match(conn, match_id)
    if not match:
        conn.close()
        flash("Match not found.")
        return redirect(url_for("matches"))

    innings = get_current_innings(conn, match_id)

    if not innings:
        conn.close()
        flash("Innings not found.")
        return redirect(url_for("matches"))

    batsmen = conn.execute(
        "SELECT * FROM players WHERE team_id=? ORDER BY name",
        (innings["batting_team_id"],)
    ).fetchall()
    bowlers = conn.execute(
        "SELECT * FROM players WHERE team_id=? ORDER BY name",
        (innings["bowling_team_id"],)
    ).fetchall()

    if request.method == "POST" and match["status"] == "LIVE":
        batsman_id = int(request.form["batsman_id"])
        bowler_id = int(request.form["bowler_id"])
        runs = int(request.form["runs"])
        extra_type = request.form.get("extra_type", "")
        extra_runs = int(request.form.get("extra_runs") or 0)
        is_wicket = 1 if request.form.get("is_wicket") == "yes" else 0
        wicket_player_id = request.form.get("wicket_player_id") or None
        note = request.form.get("note", "")

        legal_ball = 0 if extra_type in ["Wide", "No Ball"] else 1
        total_runs_this_ball = runs + extra_runs
        new_balls = innings["balls"] + legal_ball
        new_runs = innings["runs"] + total_runs_this_ball
        new_wickets = innings["wickets"] + is_wicket

        over_no = new_balls // 6
        ball_no = new_balls % 6
        if legal_ball == 1 and ball_no == 0:
            over_no -= 1
            ball_no = 6
        elif legal_ball == 0:
            over_no = innings["balls"] // 6
            ball_no = innings["balls"] % 6 + 1

        conn.execute("""
            INSERT INTO balls (
                match_id, innings_id, innings_no, over_no, ball_no,
                batsman_id, bowler_id, runs, extra_type, extra_runs,
                is_wicket, wicket_player_id, note, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            match_id, innings["id"], innings["innings_no"], over_no, ball_no,
            batsman_id, bowler_id, runs, extra_type, extra_runs,
            is_wicket, wicket_player_id, note, datetime.now().strftime("%H:%M:%S")
        ))

        ensure_batting_stat(conn, match_id, innings["id"], batsman_id)
        ensure_bowling_stat(conn, match_id, innings["id"], bowler_id)

        batsman_ball = 0 if extra_type in ["Wide"] else 1
        fours = 1 if runs == 4 else 0
        sixes = 1 if runs == 6 else 0

        conn.execute("""
            UPDATE batting_stats
            SET runs = runs + ?, balls = balls + ?, fours = fours + ?, sixes = sixes + ?
            WHERE match_id=? AND innings_id=? AND player_id=?
        """, (runs, batsman_ball, fours, sixes, match_id, innings["id"], batsman_id))

        bowler_ball = legal_ball
        bowler_runs = total_runs_this_ball
        bowler_wicket = is_wicket

        conn.execute("""
            UPDATE bowling_stats
            SET runs_given = runs_given + ?, balls = balls + ?, wickets = wickets + ?
            WHERE match_id=? AND innings_id=? AND player_id=?
        """, (bowler_runs, bowler_ball, bowler_wicket, match_id, innings["id"], bowler_id))

        if is_wicket and wicket_player_id:
            ensure_batting_stat(conn, match_id, innings["id"], int(wicket_player_id))
            conn.execute("""
                UPDATE batting_stats
                SET out_status='Out'
                WHERE match_id=? AND innings_id=? AND player_id=?
            """, (match_id, innings["id"], int(wicket_player_id)))

        innings_status = "LIVE"
        innings_completed = False
        if new_wickets >= 10 or new_balls >= match["total_overs"] * 6:
            innings_status = "COMPLETED"
            innings_completed = True

        if innings["innings_no"] == 2:
            first_innings = conn.execute("""
                SELECT * FROM innings WHERE match_id=? AND innings_no=1
            """, (match_id,)).fetchone()
            if new_runs > first_innings["runs"]:
                innings_status = "COMPLETED"
                innings_completed = True

        conn.execute("""
            UPDATE innings
            SET runs=?, wickets=?, balls=?, status=?
            WHERE id=?
        """, (new_runs, new_wickets, new_balls, innings_status, innings["id"]))

        if innings_completed and innings["innings_no"] == 1:
            existing_second = conn.execute("""
                SELECT * FROM innings WHERE match_id=? AND innings_no=2
            """, (match_id,)).fetchone()

            if not existing_second:
                conn.execute("""
                    INSERT INTO innings (
                        match_id, innings_no, batting_team_id, bowling_team_id
                    )
                    VALUES (?, 2, ?, ?)
                """, (match_id, match["second_batting_team_id"], match["first_batting_team_id"]))

            conn.execute("UPDATE matches SET current_innings=2 WHERE id=?", (match_id,))
            flash("First innings completed. Second innings started.")

        elif innings_completed and innings["innings_no"] == 2:
            complete_match_if_needed(conn, match_id)
            flash("Match completed.")
        else:
            flash("Ball added.")

        conn.commit()
        conn.close()
        return redirect(url_for("score", match_id=match_id))

    innings_list = conn.execute("""
        SELECT inn.*,
               bt.name AS batting_team_name,
               bw.name AS bowling_team_name
        FROM innings inn
        JOIN teams bt ON inn.batting_team_id=bt.id
        JOIN teams bw ON inn.bowling_team_id=bw.id
        WHERE inn.match_id=?
        ORDER BY inn.innings_no
    """, (match_id,)).fetchall()

    balls_data = conn.execute("""
        SELECT b.*,
               bat.name AS batsman_name,
               bowl.name AS bowler_name,
               wp.name AS wicket_player_name
        FROM balls b
        LEFT JOIN players bat ON b.batsman_id=bat.id
        LEFT JOIN players bowl ON b.bowler_id=bowl.id
        LEFT JOIN players wp ON b.wicket_player_id=wp.id
        WHERE b.match_id=?
        ORDER BY b.id DESC
    """, (match_id,)).fetchall()

    batting_stats = conn.execute("""
        SELECT bs.*, p.name AS player_name
        FROM batting_stats bs
        JOIN players p ON bs.player_id=p.id
        WHERE bs.match_id=? AND bs.innings_id=?
        ORDER BY bs.runs DESC
    """, (match_id, innings["id"])).fetchall()

    bowling_stats = conn.execute("""
        SELECT bs.*, p.name AS player_name
        FROM bowling_stats bs
        JOIN players p ON bs.player_id=p.id
        WHERE bs.match_id=? AND bs.innings_id=?
        ORDER BY bs.wickets DESC, bs.runs_given ASC
    """, (match_id, innings["id"])).fetchall()

    target = None
    if innings["innings_no"] == 2:
        first_innings = conn.execute("SELECT * FROM innings WHERE match_id=? AND innings_no=1", (match_id,)).fetchone()
        target = first_innings["runs"] + 1

    conn.close()

    return render_template(
        "score.html",
        match=match,
        innings=innings,
        innings_list=innings_list,
        batsmen=batsmen,
        bowlers=bowlers,
        balls=balls_data,
        batting_stats=batting_stats,
        bowling_stats=bowling_stats,
        target=target
    )


@app.route("/points")
@login_required
def points():
    conn = get_db()
    teams_data = conn.execute("SELECT * FROM teams ORDER BY name").fetchall()
    table = []

    for team in teams_data:
        played = conn.execute("""
            SELECT COUNT(*) AS c FROM matches
            WHERE status='COMPLETED' AND (team1_id=? OR team2_id=?)
        """, (team["id"], team["id"])).fetchone()["c"]

        won = conn.execute("""
            SELECT COUNT(*) AS c FROM matches
            WHERE status='COMPLETED' AND winner_team_id=?
        """, (team["id"],)).fetchone()["c"]

        tied = conn.execute("""
            SELECT COUNT(*) AS c FROM matches
            WHERE status='COMPLETED' AND winner_team_id IS NULL
            AND (team1_id=? OR team2_id=?)
        """, (team["id"], team["id"])).fetchone()["c"]

        lost = played - won - tied
        points_value = won * 2 + tied

        table.append({
            "team": team["name"],
            "played": played,
            "won": won,
            "lost": lost,
            "tied": tied,
            "points": points_value
        })

    table.sort(key=lambda x: x["points"], reverse=True)
    conn.close()
    return render_template("points.html", table=table)


@app.route("/player-stats")
@login_required
def player_stats():
    conn = get_db()
    batting = conn.execute("""
        SELECT p.name AS player_name, t.name AS team_name,
               SUM(bs.runs) AS runs,
               SUM(bs.balls) AS balls,
               SUM(bs.fours) AS fours,
               SUM(bs.sixes) AS sixes
        FROM batting_stats bs
        JOIN players p ON bs.player_id=p.id
        JOIN teams t ON p.team_id=t.id
        GROUP BY p.id
        ORDER BY runs DESC
    """).fetchall()

    bowling = conn.execute("""
        SELECT p.name AS player_name, t.name AS team_name,
               SUM(bs.runs_given) AS runs_given,
               SUM(bs.balls) AS balls,
               SUM(bs.wickets) AS wickets
        FROM bowling_stats bs
        JOIN players p ON bs.player_id=p.id
        JOIN teams t ON p.team_id=t.id
        GROUP BY p.id
        ORDER BY wickets DESC
    """).fetchall()
    conn.close()
    return render_template("player_stats.html", batting=batting, bowling=bowling)


if __name__ == "__main__":
    init_db()
    app.run(debug=True)
