import os
import sqlite3
from datetime import datetime, timedelta, time
from zoneinfo import ZoneInfo

import discord
from discord.ext import commands, tasks
from discord import app_commands
from dotenv import load_dotenv


# ==================================================
# 기본 설정
# ==================================================

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = os.getenv("GUILD_ID")
REMINDER_CHANNEL_ID = os.getenv("REMINDER_CHANNEL_ID")

if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN을 찾을 수 없습니다.")

if not GUILD_ID:
    raise RuntimeError("GUILD_ID를 찾을 수 없습니다.")

GUILD_ID = int(GUILD_ID)

if REMINDER_CHANNEL_ID:
    REMINDER_CHANNEL_ID = int(REMINDER_CHANNEL_ID)


# 한국 시간
KST = ZoneInfo("Asia/Seoul")

# 하루 목표 사이클
DAILY_GOAL = 6

# XP
XP_PER_CYCLE = 50
XP_PER_DISTRACTION = 10
XP_PER_LEVEL = 500


# ==================================================
# 데이터베이스
# ==================================================

DB_PATH = os.getenv("DB_PATH", "study.db")

db = sqlite3.connect(DB_PATH)

db.execute(
    """
    CREATE TABLE IF NOT EXISTS daily_records (
        user_id INTEGER NOT NULL,
        study_date TEXT NOT NULL,

        math INTEGER NOT NULL DEFAULT 0,
        korean INTEGER NOT NULL DEFAULT 0,
        english INTEGER NOT NULL DEFAULT 0,
        inquiry INTEGER NOT NULL DEFAULT 0,

        temptations INTEGER NOT NULL DEFAULT 0,
        xp INTEGER NOT NULL DEFAULT 0,

        PRIMARY KEY (user_id, study_date)
    )
    """
)

db.commit()


# ==================================================
# 봇 설정
# ==================================================

intents = discord.Intents.default()


class StudyBot(commands.Bot):

    def __init__(self):
        super().__init__(
            command_prefix="!",
            intents=intents
        )

    async def setup_hook(self):

        guild = discord.Object(id=GUILD_ID)

        self.tree.copy_global_to(guild=guild)

        synced = await self.tree.sync(guild=guild)

        print(f"슬래시 명령어 {len(synced)}개 등록 완료!")

        # 매일 오후 5시 알림 시작
        if not daily_reminder.is_running():
            daily_reminder.start()


bot = StudyBot()


# ==================================================
# 기본 편의 함수
# ==================================================

def today():
    return datetime.now(KST).strftime("%Y-%m-%d")


def current_hour():
    return datetime.now(KST).hour


def study_time_text(cycles):

    minutes = cycles * 50

    hours = minutes // 60
    remaining_minutes = minutes % 60

    return f"{hours}시간 {remaining_minutes}분"


def make_bar(cycles):

    completed = min(cycles, DAILY_GOAL)
    remaining = max(DAILY_GOAL - completed, 0)

    bar = "■" * completed + "□" * remaining

    if cycles > DAILY_GOAL:
        bar += f" +{cycles - DAILY_GOAL}"

    return bar


# ==================================================
# 일일 등급
# ==================================================

def get_grade(cycles):

    if cycles == 0:
        return "NO CLEAR", 0, "⬜"

    elif cycles <= 2:
        return "BRONZE", 0, "🥉"

    elif cycles <= 4:
        return "SILVER", 30, "🥈"

    elif cycles <= 6:
        return "GOLD", 100, "🥇"

    else:
        return "PERFECT", 150, "💎"


# ==================================================
# 레벨 계산
# ==================================================

def get_level(total_xp):

    return (total_xp // XP_PER_LEVEL) + 1


# ==================================================
# 칭호
# ==================================================

def get_title(level):

    titles = [
        (100, "수능 마스터"),
        (75, "장기 레이스"),
        (50, "철벽 집중"),
        (30, "몰입하는 수험생"),
        (20, "꾸준한 학습자"),
        (10, "집중 수련생"),
        (5, "루틴 수련생"),
        (1, "시작하는 수험생"),
    ]

    for required_level, title in titles:

        if level >= required_level:
            return title

    return "시작하는 수험생"


# ==================================================
# 연속 공부일 계산
# ==================================================

def calculate_streaks(user_id):

    rows = db.execute(
        """
        SELECT study_date

        FROM daily_records

        WHERE
            user_id = ?
            AND (math + korean + english + inquiry) > 0

        ORDER BY study_date ASC
        """,
        (user_id,)
    ).fetchall()

    if not rows:
        return 0, 0

    study_dates = [
        datetime.strptime(row[0], "%Y-%m-%d").date()
        for row in rows
    ]

    # 최장 연속
    longest_streak = 1
    running_streak = 1

    for i in range(1, len(study_dates)):

        previous_day = study_dates[i - 1]
        current_day = study_dates[i]

        if current_day == previous_day + timedelta(days=1):

            running_streak += 1

            longest_streak = max(
                longest_streak,
                running_streak
            )

        else:
            running_streak = 1


    # 현재 연속
    latest_study_day = study_dates[-1]
    today_date = datetime.now(KST).date()

    if latest_study_day < today_date - timedelta(days=1):

        current_streak = 0

    else:

        current_streak = 1

        for i in range(
            len(study_dates) - 1,
            0,
            -1
        ):

            current_day = study_dates[i]
            previous_day = study_dates[i - 1]

            if current_day == previous_day + timedelta(days=1):
                current_streak += 1

            else:
                break

    return current_streak, longest_streak


# ==================================================
# 매일 오후 5시 정산 알림
# ==================================================

@tasks.loop(
    time=time(
        hour=17,
        minute=0,
        tzinfo=KST
    )
)
async def daily_reminder():

    if REMINDER_CHANNEL_ID is None:

        print(
            "REMINDER_CHANNEL_ID가 없어 "
            "오후 5시 알림을 보낼 수 없습니다."
        )

        return


    channel = bot.get_channel(
        REMINDER_CHANNEL_ID
    )


    # 캐시에 채널이 없으면 직접 가져오기
    if channel is None:

        try:
            channel = await bot.fetch_channel(
                REMINDER_CHANNEL_ID
            )

        except Exception as error:

            print(
                f"알림 채널을 찾지 못했습니다: {error}"
            )

            return


    message = (
        "@everyone\n\n"
        "📚 **오늘의 공부 정산 시간입니다!**\n\n"
        "오늘 포스트잇에 기록한 사이클을 확인하고 "
        "`/정산`으로 하루 공부를 기록해 주세요.\n\n"
        "✅ 수학\n"
        "✅ 국어\n"
        "✅ 영어\n"
        "✅ 탐구\n"
        "🛡️ 집중 방해 극복 횟수\n\n"
        "**오늘의 기록을 남기고 하루를 마무리하세요.**"
    )


    try:

        await channel.send(
            message,
            allowed_mentions=discord.AllowedMentions(
                everyone=True
            )
        )

        print("오후 5시 공부 정산 알림 전송 완료!")

    except Exception as error:

        print(
            f"오후 5시 알림 전송 실패: {error}"
        )


@daily_reminder.before_loop
async def before_daily_reminder():

    await bot.wait_until_ready()


# ==================================================
# 로그인 확인
# ==================================================

@bot.event
async def on_ready():

    print("-------------------------")
    print("봇 로그인 성공!")
    print(f"봇 이름: {bot.user}")
    print("-------------------------")


# ==================================================
# /테스트
# ==================================================

@bot.tree.command(
    name="테스트",
    description="공부 봇이 정상 작동하는지 확인합니다."
)
async def test(interaction: discord.Interaction):

    await interaction.response.send_message(
        "✅ 공부 봇 연결 성공!"
    )


# ==================================================
# /정산
# ==================================================

@bot.tree.command(
    name="정산",
    description="오늘 공부한 사이클을 기록합니다."
)
@app_commands.describe(
    수학="수학 공부 사이클 수",
    국어="국어 공부 사이클 수",
    영어="영어 공부 사이클 수",
    탐구="탐구 공부 사이클 수",
    집중방해="집중 방해를 이겨낸 횟수"
)
async def settlement(
    interaction: discord.Interaction,
    수학: int = 0,
    국어: int = 0,
    영어: int = 0,
    탐구: int = 0,
    집중방해: int = 0
):

    # 오후 5시 이전 정산 금지
    if current_hour() < 17:

        await interaction.response.send_message(
            "🔒 **아직 정산 시간이 아닙니다.**\n\n"
            "오전 9시 ~ 오후 5시는 공부 시간입니다.\n"
            "지금은 포스트잇에 사이클만 기록하세요.\n\n"
            "**오후 5시 이후 `/정산`을 사용하세요.**",
            ephemeral=True
        )

        return


    # 음수 방지
    numbers = [
        수학,
        국어,
        영어,
        탐구,
        집중방해
    ]

    if any(number < 0 for number in numbers):

        await interaction.response.send_message(
            "❌ 0보다 작은 숫자는 입력할 수 없습니다.",
            ephemeral=True
        )

        return


    # 오늘 계산
    total_cycles = (
        수학
        + 국어
        + 영어
        + 탐구
    )


    grade, grade_bonus, grade_icon = get_grade(
        total_cycles
    )


    study_xp = (
        total_cycles
        * XP_PER_CYCLE
    )


    distraction_xp = (
        집중방해
        * XP_PER_DISTRACTION
    )


    total_xp_today = (
        study_xp
        + distraction_xp
        + grade_bonus
    )


    # ==================================================
    # 저장 전 전체 XP
    # ==================================================

    previous_total_result = db.execute(
        """
        SELECT COALESCE(SUM(xp), 0)

        FROM daily_records

        WHERE user_id = ?
        """,
        (interaction.user.id,)
    ).fetchone()


    previous_total_xp = (
        previous_total_result[0]
        or 0
    )


    # 기존 오늘 기록
    existing_today = db.execute(
        """
        SELECT xp

        FROM daily_records

        WHERE
            user_id = ?
            AND study_date = ?
        """,
        (
            interaction.user.id,
            today()
        )
    ).fetchone()


    existing_today_xp = (
        existing_today[0]
        if existing_today
        else 0
    )


    previous_level = get_level(
        previous_total_xp
    )


    new_total_xp = (
        previous_total_xp
        - existing_today_xp
        + total_xp_today
    )


    new_level = get_level(
        new_total_xp
    )


    # ==================================================
    # DB 저장
    #
    # DB 컬럼명 temptations는 기존 기록 호환을 위해
    # 그대로 사용한다.
    # 사용자에게는 "집중 방해"라고 표시한다.
    # ==================================================

    db.execute(
        """
        INSERT INTO daily_records (
            user_id,
            study_date,
            math,
            korean,
            english,
            inquiry,
            temptations,
            xp
        )

        VALUES (?, ?, ?, ?, ?, ?, ?, ?)

        ON CONFLICT(user_id, study_date)
        DO UPDATE SET

            math = excluded.math,
            korean = excluded.korean,
            english = excluded.english,
            inquiry = excluded.inquiry,
            temptations = excluded.temptations,
            xp = excluded.xp
        """,
        (
            interaction.user.id,
            today(),
            수학,
            국어,
            영어,
            탐구,
            집중방해,
            total_xp_today
        )
    )

    db.commit()


    # streak
    current_streak, longest_streak = calculate_streaks(
        interaction.user.id
    )


    # ==================================================
    # 정산 화면
    # ==================================================

    embed = discord.Embed(
        title=f"{grade_icon} TODAY {grade}",
        description=(
            f"**{make_bar(total_cycles)}**\n\n"
            f"오늘 **{total_cycles}사이클** 완료"
        )
    )


    embed.add_field(
        name="⏱️ 순공 시간",
        value=f"**{study_time_text(total_cycles)}**",
        inline=True
    )


    embed.add_field(
        name="🔥 연속 공부",
        value=f"**{current_streak}일**",
        inline=True
    )


    embed.add_field(
        name="📚 과목별 기록",
        value=(
            f"수학 : **{수학}**\n"
            f"국어 : **{국어}**\n"
            f"영어 : **{영어}**\n"
            f"탐구 : **{탐구}**"
        ),
        inline=False
    )


    embed.add_field(
        name="🛡️ 집중 방해 극복",
        value=f"**{집중방해}회**",
        inline=True
    )


    embed.add_field(
        name="⭐ XP 획득",
        value=(
            f"공부 : **+{study_xp} XP**\n"
            f"집중 방해 극복 : **+{distraction_xp} XP**\n"
            f"{grade} 보너스 : **+{grade_bonus} XP**\n\n"
            f"오늘 총 획득 : **+{total_xp_today} XP**"
        ),
        inline=False
    )


    # 레벨업
    if new_level > previous_level:

        new_title = get_title(
            new_level
        )

        embed.add_field(
            name="🎉 LEVEL UP!",
            value=(
                f"**LEVEL {new_level} 달성!**\n\n"
                f"현재 칭호\n"
                f"「**{new_title}**」"
            ),
            inline=False
        )


    await interaction.response.send_message(
        embed=embed
    )


# ==================================================
# /오늘
# ==================================================

@bot.tree.command(
    name="오늘",
    description="오늘 저장한 공부 기록을 확인합니다."
)
async def check_today(
    interaction: discord.Interaction
):

    result = db.execute(
        """
        SELECT
            math,
            korean,
            english,
            inquiry,
            temptations,
            xp

        FROM daily_records

        WHERE
            user_id = ?
            AND study_date = ?
        """,
        (
            interaction.user.id,
            today()
        )
    ).fetchone()


    if result is None:

        await interaction.response.send_message(
            "📭 **오늘은 아직 정산된 공부 기록이 없습니다.**\n\n"
            "오후 5시 이후 `/정산`으로 오늘 공부를 기록해 주세요.",
            ephemeral=True
        )

        return


    (
        math,
        korean,
        english,
        inquiry,
        distractions,
        xp
    ) = result


    total_cycles = (
        math
        + korean
        + english
        + inquiry
    )


    grade, grade_bonus, grade_icon = get_grade(
        total_cycles
    )


    current_streak, longest_streak = calculate_streaks(
        interaction.user.id
    )


    embed = discord.Embed(
        title=f"{grade_icon} 오늘의 공부 기록",
        description=(
            f"**{grade}**\n"
            f"{make_bar(total_cycles)}"
        )
    )


    embed.add_field(
        name="✅ 오늘 완료",
        value=f"**{total_cycles} / {DAILY_GOAL} 사이클**",
        inline=True
    )


    embed.add_field(
        name="⏱️ 순공 시간",
        value=f"**{study_time_text(total_cycles)}**",
        inline=True
    )


    embed.add_field(
        name="🔥 연속 공부",
        value=f"**{current_streak}일째**",
        inline=True
    )


    embed.add_field(
        name="📚 과목별",
        value=(
            f"수학 : **{math}**\n"
            f"국어 : **{korean}**\n"
            f"영어 : **{english}**\n"
            f"탐구 : **{inquiry}**"
        ),
        inline=False
    )


    embed.add_field(
        name="🛡️ 집중 방해 극복",
        value=f"**{distractions}회**",
        inline=True
    )


    embed.add_field(
        name="⭐ 오늘 XP",
        value=f"**{xp} XP**",
        inline=True
    )


    await interaction.response.send_message(
        embed=embed
    )


# ==================================================
# /기록
# ==================================================

@bot.tree.command(
    name="기록",
    description="지금까지의 누적 공부 기록을 확인합니다."
)
async def records(
    interaction: discord.Interaction
):

    user_id = interaction.user.id


    current_streak, longest_streak = calculate_streaks(
        user_id
    )


    totals = db.execute(
        """
        SELECT

            COUNT(
                CASE
                    WHEN (math + korean + english + inquiry) > 0
                    THEN 1
                END
            ),

            SUM(math + korean + english + inquiry),
            SUM(math),
            SUM(korean),
            SUM(english),
            SUM(inquiry),
            SUM(temptations),
            SUM(xp)

        FROM daily_records

        WHERE user_id = ?
        """,
        (user_id,)
    ).fetchone()


    study_days = totals[0] or 0
    total_cycles = totals[1] or 0

    total_math = totals[2] or 0
    total_korean = totals[3] or 0
    total_english = totals[4] or 0
    total_inquiry = totals[5] or 0

    total_distractions = totals[6] or 0
    total_xp = totals[7] or 0


    # 레벨
    level = get_level(
        total_xp
    )

    title = get_title(
        level
    )


    current_level_xp = (
        total_xp
        % XP_PER_LEVEL
    )


    xp_bar_count = min(
        current_level_xp // 50,
        10
    )


    xp_bar = (
        "■" * xp_bar_count
        + "□" * (10 - xp_bar_count)
    )


    # 최근 7개 기록
    recent = db.execute(
        """
        SELECT
            study_date,
            math + korean + english + inquiry

        FROM daily_records

        WHERE user_id = ?

        ORDER BY study_date DESC

        LIMIT 7
        """,
        (user_id,)
    ).fetchall()


    if recent:

        recent_text = ""


        for date, cycles in reversed(recent):

            grade, bonus, grade_icon = get_grade(
                cycles
            )


            recent_text += (
                f"`{date[5:]}` "
                f"{grade_icon} "
                f"**{cycles}사이클** "
                f"· {grade}\n"
            )


    else:

        recent_text = "아직 공부 기록이 없습니다."


    # ==================================================
    # 화면
    # ==================================================

    embed = discord.Embed(
        title="🏆 STUDY RECORD",
        description=(
            f"**LEVEL {level}**\n"
            f"「**{title}**」\n\n"
            f"{xp_bar}\n"
            f"{current_level_xp} / {XP_PER_LEVEL} XP"
        )
    )


    embed.add_field(
        name="📅 공부한 날",
        value=f"**{study_days}일**",
        inline=True
    )


    embed.add_field(
        name="🔥 현재 연속",
        value=f"**{current_streak}일**",
        inline=True
    )


    embed.add_field(
        name="🏅 최장 연속",
        value=f"**{longest_streak}일**",
        inline=True
    )


    embed.add_field(
        name="✅ 누적 사이클",
        value=f"**{total_cycles} 사이클**",
        inline=True
    )


    embed.add_field(
        name="⏱️ 누적 순공",
        value=f"**{study_time_text(total_cycles)}**",
        inline=True
    )


    embed.add_field(
        name="🛡️ 집중 방해 극복",
        value=f"**{total_distractions}회**",
        inline=True
    )


    embed.add_field(
        name="📚 과목별 누적",
        value=(
            f"수학 : **{total_math} 사이클**\n"
            f"국어 : **{total_korean} 사이클**\n"
            f"영어 : **{total_english} 사이클**\n"
            f"탐구 : **{total_inquiry} 사이클**"
        ),
        inline=False
    )


    embed.add_field(
        name="⭐ 총 XP",
        value=f"**{total_xp} XP**",
        inline=True
    )


    embed.add_field(
        name="📊 최근 기록",
        value=recent_text,
        inline=False
    )


    await interaction.response.send_message(
        embed=embed
    )


# ==================================================
# 실행
# ==================================================

bot.run(TOKEN)