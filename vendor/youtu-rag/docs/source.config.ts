import {
  defineConfig,
  defineDocs,
} from 'fumadocs-mdx/config';

// You can customise Zod schemas for frontmatter and `meta.json` here
// see https://fumadocs.vercel.app/docs/mdx/collections#define-docs
export const docs = defineDocs({
  docs: {
    // Use default schema
  },
  meta: {
    // Use default schema
  },
});

export default defineConfig({
  mdxOptions: {
    // MDX options
  },
});
