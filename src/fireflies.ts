import { GraphQLClient, gql } from "graphql-request";
import { config } from "./config";

const client = new GraphQLClient(config.graphqlEndpoint, {
  headers: {
    Authorization: `Bearer ${config.firefliesApiKey}`,
  },
});

export interface Sentence {
  text: string;
  speaker_name: string;
  start_time: number;
  end_time: number;
}

export interface TranscriptSummary {
  keywords: string[];
  action_items: string[];
}

export interface Transcript {
  id: string;
  title: string;
  date: string;
  duration: number;
  participants: string[];
  sentences: Sentence[];
  summary: TranscriptSummary;
}

export interface TranscriptListItem {
  id: string;
  title: string;
  date: string;
  duration: number;
}

const GET_TRANSCRIPT = gql`
  query Transcript($transcriptId: String!) {
    transcript(id: $transcriptId) {
      id
      title
      date
      duration
      participants
      sentences {
        text
        speaker_name
        start_time
        end_time
      }
      summary {
        keywords
        action_items
      }
    }
  }
`;

const LIST_TRANSCRIPTS = gql`
  query Transcripts($limit: Int, $skip: Int, $fromDate: DateTime, $toDate: DateTime) {
    transcripts(limit: $limit, skip: $skip, fromDate: $fromDate, toDate: $toDate) {
      id
      title
      date
      duration
    }
  }
`;

export async function getTranscript(id: string): Promise<Transcript> {
  const data = await client.request<{ transcript: Transcript }>(GET_TRANSCRIPT, {
    transcriptId: id,
  });
  return data.transcript;
}

export async function listTranscripts(options: {
  limit?: number;
  skip?: number;
  fromDate?: string;
  toDate?: string;
} = {}): Promise<TranscriptListItem[]> {
  const data = await client.request<{ transcripts: TranscriptListItem[] }>(LIST_TRANSCRIPTS, {
    limit: options.limit ?? 50,
    skip: options.skip ?? 0,
    fromDate: options.fromDate,
    toDate: options.toDate,
  });
  return data.transcripts;
}

export async function listAllTranscripts(): Promise<TranscriptListItem[]> {
  const all: TranscriptListItem[] = [];
  let skip = 0;
  const limit = 50;

  while (true) {
    console.log(`  Listing transcripts (skip=${skip})...`);
    const batch = await listTranscripts({ limit, skip });
    if (batch.length === 0) break;
    all.push(...batch);
    if (batch.length < limit) break;
    skip += limit;
  }

  return all;
}
