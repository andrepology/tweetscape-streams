from gettext import install
import os
import pandas as pd
from dotenv import load_dotenv
from twarc import Twarc2
from twarc_csv import DataFrameConverter
from requests.exceptions import HTTPError

requirements to install

pandas 
python-dotenv 
twarc
twarc_csv 

load_dotenv()


twarc_client = Twarc2(
    consumer_key=os.environ["consumer_key"],
    consumer_secret=os.environ["consumer_secret"],
    access_token=os.environ["access_token"],
    access_token_secret=os.environ["access_token_secret"],
)

converter = DataFrameConverter("tweets", allow_duplicates=True)

def pull_tweets(client, username, extract_features=True, max_tweets=1000, start_time=None, end_time=None):
    df_tweets = None
    df_ref_tweets = None

    print(f"pulling tweets for user {username}")

    id_res = [i for i in client.user_lookup(users=[username], usernames=True)][0]
    if "errors" in id_res:
        print(f"user '{username}' not found... skipping")
        return None, None, None
    else: 
        id_ = id_res["data"][0]["id"]
    # id_ =  [i for i in client.user_lookup(users=[username], usernames=True)][0]["data"][0]["id"]
    timeline_gen = client.timeline(id_, max_results=100, start_time=start_time, end_time=end_time)
    try: 
        max_pages = max_tweets // 100
        cur_page = 0

        for res in timeline_gen:
            df_tweets_next = converter.process([res])
            
            if df_tweets is None:
                df_tweets = df_tweets_next
            else: 
                df_tweets = pd.concat([df_tweets, df_tweets_next])
                
            if "tweets" in res["includes"]:
                df_ref_tweets_next = converter.process(res["includes"]["tweets"])
                if df_ref_tweets is None:
                    df_ref_tweets = df_ref_tweets_next
                else: 
                    df_ref_tweets = pd.concat([df_ref_tweets, df_ref_tweets_next]) 
            cur_page += 1
            if cur_page >= max_pages:
                break
    except HTTPError as err: 
        print(f"400 client error for id {id_}... skipping")
        return username, None, None
    print("printing dfs")
    if df_tweets is None: 
        return username, None, None # TODO: make this more rigorous

    print(type(df_tweets))
    print(df_tweets.shape)

    if extract_features: 
        for df_ in [df_tweets, df_ref_tweets]:
            if df_ is not None: 
                df_["entities.mentions.usernames"] = df_["entities.mentions"].apply(extract_usernames)
                df_["entities.mentions.num_mentions"] = df_["entities.mentions"].apply(extract_num_mentions)
                df_["entities.mentions.double_mention"] = df_["entities.mentions"].apply(extract_double_mention)
                df_["tweet_type"] = df_.apply(lambda x: extract_tweet_type(x), axis=1)
                df_["tweet_link"] = df_.apply(lambda row: f"https://twitter.com/{row['author.username']}/status/{row.id}", axis=1)
                df_.loc[:, "created_at"] = pd.to_datetime(df_.loc[:, "created_at"], utc=True)
                df_["created_at.hour"] = df_["created_at"].dt.floor('h')
    if df_ref_tweets is not None: 
        df_ref_tweets["referencer.username"] = username # make it possible for me to get the id of the account who referenced this tweet
    return username, df_tweets, df_ref_tweets 


def extract_tweet_type(row):
    """
    Current Categories are 
    reply - reply that doesn't include a quoted tweet (I could expand to include mentions, but I don't feel like it right now)                 
    rt                     
    qt,reply - reply tweet that includes a quoted tweet
    standalone - classic tweet, just text          
    self-reply - reply to yourself          
    qt                     
    standalone,mention - classic tweet, but you also mention another user  
    qt,self-reply - quote tweet in reply to your own account      
    qt,mention - quote tweet where you mention another account, not a reply 
    """
    standalone = "standalone,"
    reply = "reply,"
    rt = "rt,"
    qt = "qt,"
    mention = "mention,"
    
    type_str = ""
    
    ## Standalone means that there is no in_reply_to_user_id or a referenced_tweet
    if (
        pd.isna(row["in_reply_to_user_id"]) and 
        pd.isna(row['referenced_tweets.replied_to.id']) and 
        pd.isna(row['referenced_tweets.retweeted.id']) and 
        pd.isna(row['referenced_tweets.quoted.id'])
    ):
        type_str += standalone
        
        if not pd.isna(row["entities.mentions"]):
            type_str += mention
    
    ## I think this is a special case where user starts there own standlone tweet with a mention, so twitter reads it weird
    # Here is an example: https://twitter.com/deepfates/status/1536434435075280898, it starts with a mention, with twitter reads into the in_reply_to_user_id field
    elif pd.isna(row['referenced_tweets.replied_to.id']) and not pd.isna(row["in_reply_to_user_id"]):
        type_str += standalone
        type_str += mention 
    
    ## Retweet
    elif not pd.isna(row['referenced_tweets.retweeted.id']):
        type_str += rt 
        if not pd.isna(row["entities.mentions"]):
            type_str += mention
    
    ## Quote Tweet 
    elif not pd.isna(row['referenced_tweets.quoted.id']):
        type_str += qt
        if (
            pd.isna(row["in_reply_to_user_id"]) and 
            pd.isna(row['referenced_tweets.replied_to.id']) and 
            pd.isna(row['referenced_tweets.retweeted.id']) and 
            not pd.isna(row["entities.mentions"])
        ): 
            type_str += mention 

    ### Replies

    ## Self-Reply
    if row["author.id"] == row["in_reply_to_user_id"]:
        type_str += "self-reply,"
        if not pd.isna(row["entities.mentions"]):
            type_str += mention

    ## Replies
    elif not pd.isna(row['referenced_tweets.replied_to.id']):
        type_str += reply
        
    return type_str[:-1]